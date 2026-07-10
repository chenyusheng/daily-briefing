#!/usr/bin/env python3
"""
Update events data for the portfolio event timeline.
- Advances `today` date to current date
- Marks past upcoming events as "done"
- Recalculates stats
- Optionally merges new events from a temp file (written by LLM cron)
- Git push to GitHub Pages

Usage:
  python3 update_events_data.py                     # basic update
  python3 update_events_data.py --merge new_events.json  # merge new events + update
"""
import json, os, sys, datetime, subprocess

BASE = os.path.expanduser("~/daily-briefing")
DATA_PATH = os.path.join(BASE, "data", "events.json")
TODAY = datetime.date.today().isoformat()  # 2026-07-10

def load_json(path):
    with open(path) as f:
        return json.load(f)

def save_json(path, data):
    # Write with stable key ordering and ensure_ascii=False for Chinese
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')

def days_until(date_str):
    """Calculate days from today to date_str. date_str can be YYYY-MM-DD or YYYY-MM."""
    if not date_str:
        return None
    try:
        d = datetime.date.fromisoformat(date_str)
        return (d - datetime.date.today()).days
    except ValueError:
        # Partial date like "2026-07" — approximate to month end
        try:
            y, m = date_str.split('-')
            d = datetime.date(int(y), int(m), 1) + datetime.timedelta(days=20)
            return (d - datetime.date.today()).days
        except:
            return None

def merge_new_events(data, new_events_path):
    """Merge new events from a JSON file. Avoids duplicates by checking event id."""
    if not os.path.exists(new_events_path):
        return data, False

    with open(new_events_path) as f:
        new_data = json.load(f)

    new_events = new_data.get('events', [])
    if not new_events:
        os.remove(new_events_path)
        return data, False

    existing_ids = set(e['id'] for e in data['events'])
    added = 0
    for ev in new_events:
        if ev['id'] not in existing_ids:
            data['events'].append(ev)
            existing_ids.add(ev['id'])
            added += 1

    # Update stocks if any new ones
    existing_stock_ids = set(s['id'] for s in data['stocks'])
    for s in new_data.get('stocks', []):
        if s['id'] not in existing_stock_ids:
            data['stocks'].append(s)

    os.remove(new_events_path)
    return data, added > 0

def recalc_stats(events, today):
    """Recalculate stats based on current events and today's date."""
    today_dt = datetime.date.fromisoformat(today) if isinstance(today, str) else today
    today_iso = today_dt.isoformat()

    critical = 0
    upcoming_7d = 0
    upcoming_30d = 0
    monitoring = 0

    for ev in events:
        if ev['status'] == 'monitoring':
            monitoring += 1
            continue
        if ev['importance'] == 5:
            critical += 1
        d = days_until(ev['date'])
        if d is not None and 0 <= d <= 7:
            upcoming_7d += 1
        if d is not None and 0 <= d <= 30:
            upcoming_30d += 1

    return {
        "total_events": len(events),
        "upcoming_7d": upcoming_7d,
        "upcoming_30d": upcoming_30d,
        "critical_events": critical,
        "monitoring": monitoring
    }

def mark_past_events(events, today):
    """Mark events with dates before today as 'done' if they were 'upcoming' or 'today'."""
    today_dt = datetime.date.fromisoformat(today) if isinstance(today, str) else today
    today_iso = today_dt.isoformat()
    changed = 0

    for ev in events:
        if ev['status'] in ('upcoming', 'today'):
            d = days_until(ev['date'])
            if d is not None and d < 0:
                ev['status'] = 'done'
                ev['date_label'] = '✅ ' + ev['date_label']
                changed += 1
            elif d == 0 and ev['status'] != 'today':
                ev['status'] = 'today'
                changed += 1

    return events, changed

def git_push():
    """Git add, commit, push with automatic messages."""
    os.chdir(BASE)
    result = subprocess.run(
        ["git", "add", "data/events.json"],
        capture_output=True, text=True, timeout=15
    )
    if result.returncode != 0:
        return f"git add failed: {result.stderr.strip() or result.stdout.strip()}"

    # Check if there's anything to commit
    result = subprocess.run(
        ["git", "status", "--porcelain", "data/events.json"],
        capture_output=True, text=True, timeout=10
    )
    if not result.stdout.strip():
        return "no changes to push"

    result = subprocess.run(
        ["git", "commit", "-m", f"chore: auto-update events timeline [{TODAY}]"],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode != 0 and "nothing to commit" not in result.stdout:
        return f"git commit failed: {result.stderr.strip() or result.stdout.strip()}"

    result = subprocess.run(
        ["git", "push"],
        capture_output=True, text=True, timeout=20
    )
    if result.returncode != 0:
        return f"git push failed: {result.stderr.strip() or result.stdout.strip()}"

    return "ok"

def main():
    if not os.path.exists(DATA_PATH):
        print(f"ERROR: {DATA_PATH} not found")
        sys.exit(1)

    data = load_json(DATA_PATH)
    today = TODAY
    old_today = data.get('today', '')

    changes = []

    # Step 1: Mark past events
    data['events'], changed = mark_past_events(data['events'], today)
    if changed:
        changes.append(f"marked {changed} events as done")

    # Step 2: Merge new events if --merge flag
    merged = False
    if '--merge' in sys.argv:
        idx = sys.argv.index('--merge')
        if idx + 1 < len(sys.argv):
            merge_path = sys.argv[idx + 1]
            data, merged = merge_new_events(data, merge_path)
            if merged:
                changes.append("merged new events")

    # Step 3: Update metadata
    data['today'] = today
    now_str = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    data['updated'] = now_str

    # Step 4: Recalculate stats
    data['stats'] = recalc_stats(data['events'], today)

    # Step 5: Write
    save_json(DATA_PATH, data)
    changes.append(f"today: {old_today} → {today}")
    changes.append(f"stats updated: {data['stats']}")

    # Step 6: Git push
    push_result = git_push()
    changes.append(f"git: {push_result}")

    # Output summary
    print(f"[{now_str}] Events timeline updated")
    for c in changes:
        print(f"  • {c}")

if __name__ == '__main__':
    main()
