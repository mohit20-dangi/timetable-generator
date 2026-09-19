from typing import Any, Dict, List, Optional
from pymongo.database import Database
from pymongo.collection import Collection


class Repository:
    """Thin CRUD wrapper around a Mongo collection.

    Every entity uses its own natural string id as Mongo's `_id`, so callers
    work with plain dicts shaped like the API's Create/Response models (an
    `id` field, never `_id`) and this class handles the translation.
    """

    def __init__(self, db: Database, collection_name: str):
        self.collection: Collection = db[collection_name]

    @staticmethod
    def _to_doc(data: Dict[str, Any]) -> Dict[str, Any]:
        doc = dict(data)
        doc["_id"] = doc.pop("id")
        return doc

    @staticmethod
    def _from_doc(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if doc is None:
            return None
        result = dict(doc)
        result["id"] = result.pop("_id")
        return result

    def list_all(self, filter_: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        return [self._from_doc(d) for d in self.collection.find(filter_ or {})]

    def get(self, id_: str) -> Optional[Dict[str, Any]]:
        return self._from_doc(self.collection.find_one({"_id": id_}))

    def exists(self, id_: str) -> bool:
        return self.collection.count_documents({"_id": id_}, limit=1) > 0

    def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        doc = self._to_doc(data)
        self.collection.insert_one(doc)
        return self._from_doc(doc)

    def update(self, id_: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        patch = {k: v for k, v in patch.items() if k != "id"}
        result = self.collection.find_one_and_update(
            {"_id": id_}, {"$set": patch}, return_document=True
        )
        return self._from_doc(result)

    def delete(self, id_: str) -> bool:
        result = self.collection.delete_one({"_id": id_})
        return result.deleted_count > 0


def next_sequence(db: Database, name: str) -> int:
    """Classic Mongo auto-increment pattern for entities that need integer ids
    (e.g. timetable runs), backed by a small `counters` collection."""
    doc = db.counters.find_one_and_update(
        {"_id": name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    return doc["seq"]
