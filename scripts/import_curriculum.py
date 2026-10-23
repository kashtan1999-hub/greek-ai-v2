import json
from datetime import datetime, timezone
from pathlib import Path

from services.supabase_client import supabase


DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "curriculum.json"


def import_curriculum() -> None:
    records = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    from services.course_sequence import BLOCK_ORDER
    if [row["block"] for row in records] != BLOCK_ORDER or any(not str(row.get("content") or "").strip() for row in records):
        raise ValueError("Curriculum must contain exactly 35 ordered blocks with nonempty content")
    created = 0
    updated = 0

    for record in records:
        existing = (
            supabase.table("Curriculum")
            .select("id")
            .eq("block", record["block"])
            .eq("content_type", record["content_type"])
            .limit(1)
            .execute()
        )
        payload = {
            **record,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        if existing.data:
            payload.pop("created_at", None)
            (
                supabase.table("Curriculum")
                .update(payload)
                .eq("id", existing.data[0]["id"])
                .execute()
            )
            updated += 1
        else:
            supabase.table("Curriculum").insert(payload).execute()
            created += 1

        print(f"Imported block {record['block']}")

    print(f"Done. Created: {created}, updated: {updated}, total: {len(records)}")
    print("35 client source lessons imported. Old database rows are not deleted by this script.")


if __name__ == "__main__":
    import_curriculum()

