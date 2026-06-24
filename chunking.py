from pathlib import Path
import hashlib
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings 
from langchain_core.documents import Document


embeddings = OpenAIEmbeddings(model="text-embedding-3-small",
                              api_key ="")

#Assigning folder path 
folder_path = Path("./corpus")
CHROMA_DIR = "./chroma_db"
target_keys = ["Title","Journal","PMCID","PMID","Source","Tier","License"]

vector_store = Chroma(
                collection_name="GlucoCite",
                embedding_function=embeddings,
                persist_directory=CHROMA_DIR,
            )

#Text splitter
text_splitter = RecursiveCharacterTextSplitter(chunk_size=512,chunk_overlap=76)

#Looping over the text using rglob 
for text_file in folder_path.rglob("*.txt"):
    with open(text_file, "r", encoding="utf-8") as file:
        content = file.read()

    if "------------------------------------------------------------" not in content:
        continue
    #Splitting the head(metadata) and body 
    head, body = content.split("------------------------------------------------------------",1)
    #Assigning target keys in metadata to parse in meta_data dictionary
    meta_data = {} 
    #Looping through head(meta_data)
    for line in head.splitlines(): 
        line = line.strip() 
        for key in target_keys:
              if line.startswith(f"{key}:"):
                print("MATCHED:", key, "on line:", line)
                _, value = line.split(":",1)
                meta_data[key] = value.strip()
                break 
        
    meta_data["file_name"] = text_file.name

    doc_id = meta_data.get("PMCID") or meta_data.get("PMID") or text_file.name
    # Diagnosing 
    #if "PMCID" not in meta_data and "PMID" not in meta_data:
     #   print("NO ID FOUND:", text_file.name)

    parent_doc = Document(page_content=body.strip(),metadata=meta_data)
    #Chunking the content in the body 
    chunks = text_splitter.split_documents([parent_doc])

    langchain_docs = []
    chunk_ids = [] 
    #Combining the metadata with each chunk 
    for index , chunk in enumerate(chunks):
        #Hashing and Generating SHA-256 Hash
        normalized = f"{doc_id}_{index}_{chunk.page_content}"
        chunk_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        #Metadata Dictionary 
        chunk.metadata["Chunk_Index"] = index + 1 
        langchain_docs.append(chunk)
        chunk_ids.append(chunk_hash)
        
    if langchain_docs:
        vector_store.add_documents(documents=langchain_docs, ids=chunk_ids)

print("All Chunks parsed and ingested successfully!")


            


