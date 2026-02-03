# backend/utils/helpers.py
def doc_to_dict(doc: dict) -> dict:
    """Converts MongoDB document to a JSON-serializable dict."""
    if not doc:
        return {}
    
    # Convert _id to string
    if "_id" in doc:
        doc["id"] = str(doc["_id"])
        del doc["_id"]
    
    # Convert any other ObjectIds
    for k, v in doc.items():
        if str(type(v)) == "<class 'bson.objectid.ObjectId'>":
            doc[k] = str(v)
            
    return doc