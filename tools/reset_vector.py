import chromadb

client = chromadb.PersistentClient(path="./vector_store")

try:
    client.delete_collection("qa_docs")
except:
    pass

client.get_or_create_collection("qa_docs")

print("Vector DB reset")