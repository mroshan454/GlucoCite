from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
import os

embeddings = OpenAIEmbeddings(
    model="text-embedding-3-small",
    api_key="")
vector_store = Chroma(
    collection_name="GlucoCite",
    embedding_function=embeddings,
    persist_directory="./chroma_db",
)

print("Chunk count:", vector_store._collection.count())

results = vector_store.similarity_search("type 2 diabetes lifestyle and diet", k=5)
for r in results:
    print(r.metadata.get("PMCID"), r.metadata.get("PMID"), "->", r.page_content[:100])
    print("---")

