from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
import os
from dotenv import load_dotenv
import os

load_dotenv()
api_key = os.environ["OPENAI_API_KEY"]

from langchain_openai import ChatOpenAI
_llm = ChatOpenAI(model="gpt-4o-mini", api_key=api_key)

embeddings = OpenAIEmbeddings(
    model="text-embedding-3-small",
    api_key=api_key)
vector_store = Chroma(
    collection_name="GlucoCite",
    embedding_function=embeddings,
    persist_directory="./chroma_db",
)
question = "What lifestyle and diet changes help manage type 2 diabetes?"
results = vector_store.similarity_search(question, k=5)
context = "" 
for r in results:
    source = r.metadata.get("PMCID") or r.metadata.get("PMID")
    context += f"[Source:{source}] {r.page_content} \n\n"


prompt = f""" Act as a Clinical advisor or a doctor , 
 only answer the question  based on the context below {context},
 if it's not in the context , don't guess the answer and say refer to a clinician.
 Also , dont guess dosing or treatment advice , the Question is {question} , cite the sources in the answer """

def call_llm(prompt):
    response = _llm.invoke(prompt)
    return response.content


answer = call_llm(prompt)
print(answer)