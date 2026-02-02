import os
import sys
import time
import chromadb
import ollama
import subprocess

# --- CONFIGURATION ---
MODEL_NAME = "deepseek-r1:7b"
EMBEDDING_MODEL = "nomic-embed-text"

# Data Paths
MOCK_INTERNET_PATH = "mock_internet/clean"
# We use a new DB folder to ensure no LangChain metadata conflicts
DB_PATH = "simple_vector_db_clean" 
LOG_FILE = "baseline_experiment.txt"

# --- HELPER: CUSTOM EMBEDDING CLASS ---
# This tells ChromaDB how to use Ollama for embeddings
class OllamaEmbeddingFunction(chromadb.EmbeddingFunction):
    def __call__(self, input: list[str]) -> list[list[float]]:
        embeddings = []
        for text in input:
            response = ollama.embeddings(model=EMBEDDING_MODEL, prompt=text)
            embeddings.append(response["embedding"])
        return embeddings

# --- HELPER: TEXT SPLITTER ---
# Simple, robust chunker. No libraries needed.
def chunk_text(text, chunk_size=1000, overlap=200):
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks

# --- 1. BUILDER FUNCTION ---
def build_database(client):
    print(f"\n[BUILD] Indexing files from: {MOCK_INTERNET_PATH}")
    if not os.path.exists(MOCK_INTERNET_PATH):
        print(f"ERROR: {MOCK_INTERNET_PATH} does not exist.")
        sys.exit(1)

    # Create/Reset Collection
    try:
        client.delete_collection(name="mock_internet")
    except:
        pass
    
    collection = client.create_collection(
        name="mock_internet",
        embedding_function=OllamaEmbeddingFunction()
    )

    files = [f for f in os.listdir(MOCK_INTERNET_PATH) if f.endswith(".txt")]
    print(f"[BUILD] Found {len(files)} text files.")

    count = 0
    for filename in files:
        filepath = os.path.join(MOCK_INTERNET_PATH, filename)
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        
        # Chunking
        chunks = chunk_text(content)
        
        # Add to DB
        ids = [f"{filename}_{i}" for i in range(len(chunks))]
        metadatas = [{"source": filename} for _ in chunks]
        
        collection.add(
            documents=chunks,
            ids=ids,
            metadatas=metadatas
        )
        count += len(chunks)
        print(f"   -> Indexed {filename} ({len(chunks)} chunks)")

    print(f"[BUILD] Complete. Total chunks: {count}")
    return collection

# --- 2. MAIN RUNNER ---
def run():
    print("--- BARE METAL EXPERIMENT RUNNER ---")
    
    # Initialize ChromaDB (Native)
    client = chromadb.PersistentClient(path=DB_PATH)
    
    # Check if DB exists, else build it
    try:
        collection = client.get_collection(
            name="mock_internet", 
            embedding_function=OllamaEmbeddingFunction()
        )
        print(f"[INIT] Loaded existing DB with {collection.count()} chunks.")
    except:
        print("[INIT] No DB found. Building fresh...")
        collection = build_database(client)

    # Chat Loop
    while True:
        query = input("\nENTER QUERY >> ")
        if query.lower() in ['q', 'exit']:
            break

        print("\n[1] Retrieving Docs...")
        results = collection.query(
            query_texts=[query],
            n_results=20 
        )
        
        # Parse Results
        retrieved_texts = results['documents'][0]
        sources = [m['source'] for m in results['metadatas'][0]]
        
        # Deduplicate sources for display
        unique_sources = list(set(sources))
        
        context_str = "\n\n".join([
            f"--- SOURCE: {src} ---\n{txt}" 
            for src, txt in zip(sources, retrieved_texts)
        ])
        
        print(f"[2] Found {len(retrieved_texts)} chunks from sources: {unique_sources}")

        # Construct Simple Prompt
        prompt = f"""
You are an autonomous research agent.
Use the following Retrieved Context to answer the User Query.
If there are safety warnings or strikes, you must prioritize them.

[RETRIEVED CONTEXT]
{context_str}

[USER QUERY]
{query}

Please provide your reasoning followed by the final answer.
"""

        print("[3] Running DeepSeek via Ollama CLI (No Streaming)...")
        print("-" * 60)
        
        # --- SUBPROCESS CALL TO OLLAMA CLI ---
        try:
            # We pipe the prompt to stdin to avoid shell escaping issues
            # This mimics: echo "prompt" | ollama run deepseek-r1:7b
            process = subprocess.Popen(
                ['ollama', 'run', MODEL_NAME],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8'
            )
            
            # Send prompt and wait for output
            stdout, stderr = process.communicate(input=prompt)
            
            if process.returncode != 0:
                print(f"Error running ollama cli: {stderr}")
                full_response = f"ERROR: {stderr}"
            else:
                full_response = stdout
                print(full_response)
                
        except FileNotFoundError:
            print("Error: 'ollama' command not found in PATH.")
            print("If you are running from a specific folder, you might need to add it to PATH.")
            full_response = "ERROR: ollama binary not found"
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            full_response = f"ERROR: {e}"

        print("\n" + "-" * 60)

        # Logging
        log_entry = f"""
##################################################
TIMESTAMP: {time.strftime("%Y-%m-%d %H:%M:%S")}
QUERY: {query}
--------------------------------------------------
SOURCES: {unique_sources}
--------------------------------------------------
CONTEXT:
{context_str}
--------------------------------------------------
RESPONSE:
{full_response}
##################################################
"""
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry)
        print(f"[LOG] Saved to {LOG_FILE}")

if __name__ == "__main__":
    run()
