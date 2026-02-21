import os
import json
import time
import pandas as pd
from tavily import TavilyClient

# ==========================================
# CONFIGURATION
# ==========================================
TAVILY_API_KEY = "MY_KEY"
INPUT_CSV = "20_domains_50_queries.csv"
OUTPUT_FILE = "harvested_sources-swe-focused.json"
QUERIES_PER_DOMAIN = 10

# Domains to explicitly ignore (already harvested)
COMPLETED_DOMAINS = []

# Initialize Client
tavily = TavilyClient(api_key=TAVILY_API_KEY)

def main():
    # 1. Load the Target List
    if not os.path.exists(INPUT_CSV):
        print(f"❌ Error: {INPUT_CSV} not found.")
        return

    df = pd.read_csv(INPUT_CSV)
    
    # Filter to top 10 per domain
    df_targets = df.groupby('Domain').head(QUERIES_PER_DOMAIN).reset_index(drop=True)

    # Ignore the completed domains so we don't process them again
    df_targets = df_targets[~df_targets['Domain'].isin(COMPLETED_DOMAINS)]

    # 2. Load Existing Successes
    existing_data = []
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            try:
                existing_data = json.load(f)
            except json.JSONDecodeError:
                print("⚠️ Warning: JSON file corrupted. Starting over.")
                existing_data = []

    # Create a set of already processed IDs for fast lookup
    # This prevents duplicate fetching within the remaining domains
    processed_ids = set((item['Domain'], item['Query ID']) for item in existing_data)

    print(f"📋 Targets to Process (excluding completed domains): {len(df_targets)}")
    print(f"✅ Already Harvested (total items in JSON): {len(existing_data)}")

    # 3. Identify Missing Queries
    missing_queries = []
    for _, row in df_targets.iterrows():
        if (row['Domain'], row['Query ID']) not in processed_ids:
            missing_queries.append(row)

    if not missing_queries:
        print("🎉 All remaining queries are already completed! No retries needed.")
        return

    print(f"🔄 Fetching {len(missing_queries)} pending queries sequentially...\n")

    # 4. Processing Loop (Sequential + Sleep)
    new_successes = 0

    for row in missing_queries:
        domain = row['Domain']
        query_id = row['Query ID']
        query = row['Query']

        print(f"🔍 Fetching: [{domain}] ID:{query_id}...")

        try:
            # Execute Search
            response = tavily.search(
                query=query,
                search_depth="advanced",
                max_results=5
            )

            # Extract Data
            sources_data = [
                {"url": result['url'], "title": result['title']}
                for result in response['results']
            ]

            result_obj = {
                "Domain": domain,
                "Query ID": query_id,
                "Query": query,
                "Sources": sources_data
            }

            # Append to existing data immediately
            existing_data.append(result_obj)
            new_successes += 1

            # Save progress after EVERY successful call (Safety first)
            with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                json.dump(existing_data, f, indent=4, ensure_ascii=False)

            # *** CRITICAL: SLEEP TO PREVENT RATE LIMIT BLOCKING ***
            time.sleep(1.5)

        except Exception as e:
            print(f"❌ Failed on {query_id}: {e}")
            # If we hit a rate limit, wait longer
            if "429" in str(e) or "blocked" in str(e).lower():
                print("⏳ Rate limit hit. Sleeping for 10 seconds...")
                time.sleep(10)

    print(f"\n✅ Batch Complete.")
    print(f"📊 Added {new_successes} new queries. Total in JSON: {len(existing_data)}")

if __name__ == "__main__":
    main()