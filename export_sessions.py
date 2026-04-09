"""
Export recent conversation sessions from Firestore to JSON files.
Usage: python export_sessions.py [--limit 10] [--out ./exported_sessions]
"""
import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore

def ts_to_str(ts):
    if ts is None:
        return None
    try:
        if hasattr(ts, 'seconds'):
            return datetime.utcfromtimestamp(ts.seconds).strftime('%Y-%m-%d %H:%M:%S UTC')
        return str(ts)
    except Exception:
        return str(ts)

def export(limit: int, out_dir: Path):
    # Init Firebase
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "nexar-corp-systems")
    if not firebase_admin._apps:
        cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred, {"projectId": project_id})
    db = firestore.client()

    out_dir.mkdir(parents=True, exist_ok=True)

    # Fetch conversations
    print(f"Fetching {limit} most recent conversations from Firestore…")
    docs = (
        db.collection("fleet_conversations")
        .order_by("updated_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .stream()
    )

    sessions = []
    for doc in docs:
        data = doc.to_dict()
        session_id = data.get("session_id", doc.id)

        # Fetch associated lead
        lead_doc = db.collection("fleet_leads").document(session_id).get()
        lead = lead_doc.to_dict() if lead_doc.exists else None

        # Serialize timestamps
        messages = []
        for m in data.get("messages", []):
            messages.append({
                "role": m.get("role"),
                "content": m.get("content"),
                "timestamp": ts_to_str(m.get("timestamp")),
                "cta_type": m.get("cta_type"),
            })

        session = {
            "session_id": session_id,
            "created_at": ts_to_str(data.get("created_at")),
            "updated_at": ts_to_str(data.get("updated_at")),
            "message_count": len(messages),
            "rating": data.get("rating"),
            "rating_notes": data.get("rating_notes"),
            "lead": {
                k: v for k, v in (lead or {}).items()
                if k not in ("created_at", "updated_at", "slack_notified_at", "quote_sent_at")
            } if lead else None,
            "messages": messages,
        }
        sessions.append(session)

        # Write individual session file
        fname = out_dir / f"{session_id[:12]}.json"
        with open(fname, "w") as f:
            json.dump(session, f, indent=2, default=str)

    # Write combined summary file
    summary = []
    for s in sessions:
        summary.append({
            "session_id": s["session_id"],
            "updated_at": s["updated_at"],
            "message_count": s["message_count"],
            "rating": s["rating"],
            "lead_name": (s["lead"] or {}).get("contact_name"),
            "lead_email": (s["lead"] or {}).get("contact_email"),
            "business": (s["lead"] or {}).get("business_name"),
            "cameras": (s["lead"] or {}).get("num_cameras"),
        })

    summary_file = out_dir / "_summary.json"
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\nExported {len(sessions)} sessions to {out_dir}/")
    print(f"  _summary.json — all sessions overview")
    for s in sessions:
        lead_info = ""
        if s.get("lead"):
            parts = [s["lead"].get("contact_name"), s["lead"].get("business_name")]
            lead_info = f" — {', '.join(p for p in parts if p)}" if any(parts) else ""
        print(f"  {s['session_id'][:12]}.json  {s['updated_at']}  {s['message_count']} msgs{lead_info}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10, help="Number of sessions to export (default: 10)")
    parser.add_argument("--out", type=str, default="./exported_sessions", help="Output directory")
    args = parser.parse_args()
    export(args.limit, Path(args.out))
