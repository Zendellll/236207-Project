import os
import sys
import ollama
import chromadb
import time

# --- CONFIGURATION ---
MODEL_NAME = "deepseek-r1:7b"
EMBEDDING_MODEL = "nomic-embed-text"
DB_PATH = "vector_db_clean" # Points to the folder you already built

# --- 1. SETUP DATABASE CONNECTION ---
# We connect directly to the ChromaDB folder created by your previous script.
if not os.path.exists(DB_PATH):
    print(f"Error: Database at {DB_PATH} not found.")
    sys.exit(1)

print(f"--- Connecting to Database at {DB_PATH} ---")
db_client = chromadb.PersistentClient(path=DB_PATH)

# LangChain saves data into a collection named "langchain" by default.
# We access it directly.
try:
    collection = db_client.get_collection(name="langchain")
    print(f"Loaded collection. Count: {collection.count()} documents.")
except Exception as e:
    print(f"Error loading collection: {e}")
    print("Did you build the DB using the previous script?")
    sys.exit(1)

def query_and_run(user_query):
    print(f"\nQUERY: {user_query}")
    print("-" * 50)

    # --- 2. RETRIEVAL (RAG) ---
    print("1. Embedding Query...")
    # Generate embedding for the query using the same model used for docs
    embed_response = ollama.embeddings(model=EMBEDDING_MODEL, prompt=user_query)
    query_vector = embed_response["embedding"]

    print("2. Searching Vector DB...")
    # Query Chroma directly
    results = collection.query(
        query_embeddings=[query_vector],
        n_results=5
    )

    # Extract text from results
    # results['documents'] is a list of lists (batch format), so we take index 0
    retrieved_docs = results['documents'][0]
    
    if not retrieved_docs:
        print("No documents found.")
        context = "No context available."
    else:
        # Join the docs with a simple separator
        context = "\n\n--- SOURCE DOCUMENT ---\n".join(retrieved_docs)
        print(f"Found {len(retrieved_docs)} documents.")

    # --- 3. GENERATION (DeepSeek R1) ---
    print("3. Streaming DeepSeek Response...")
    print("-" * 20 + " OUTPUT " + "-" * 20)

    # We construct the simplest prompt possible. 
    # No system instructions, no "You are a robot". Just data.
    final_prompt = f"""
Here is some information retrieved from the internet:
{context}

Based on this information, answer the following question:
{user_query}
"""

    # We use the raw 'chat' method.
    stream = ollama.chat(
        model=MODEL_NAME,
        messages=[{'role': 'user', 'content': final_prompt}],
        stream=True,
    )

    full_response = ""
    for chunk in stream:
        content = chunk['message']['content']
        print(content, end='', flush=True)
        full_response += content

    print("\n" + "=" * 50)
    
    # Save log
    with open("experiment_log_simple.txt", "a", encoding="utf-8") as f:
        f.write(f"\nQUERY: {user_query}\nRESPONSE:\n{full_response}\n{'='*50}")

if __name__ == "__main__":
    while True:
        q = input("\nEnter Question (or 'q' to quit): ")
        if q.lower() in ['q', 'exit']:
            break
        query_and_run(q)