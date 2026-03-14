
import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent))

from backend.utils.db import init_db
from backend.rag_tutor import answer_query_with_rag
from backend.core.evaluation.validator import ValidationEngine
from backend.utils.db import db_manager

async def run_benchmark():
    print("🚀 Starting RAG Benchmark Evaluation...")
    
    # 1. Initialize DB
    await init_db()
    
    # 2. Load Dataset
    data_path = "data/benchmark.json"
    if not os.path.exists(data_path):
        print(f"❌ Benchmark data not found at {data_path}")
        return

    with open(data_path, "r") as f:
        dataset = json.load(f)
        
    print(f"📊 Loaded {len(dataset)} test cases.")
    
    validator = ValidationEngine(db_manager.db)
    
    results = []
    
    # 3. Run Evaluation Loop
    for i, case in enumerate(dataset):
        query = case["question"]
        gold = case["gold_answer"]
        subject = case.get("subject", "general")
        
        print(f"\n[{i+1}/{len(dataset)}] Testing: {query}")
        
        # A. Generate Answer
        start_time = datetime.now()
        rag_result = await answer_query_with_rag(
            user_id="benchmark_runner",
            query=query,
            subject=subject
        )
        duration = (datetime.now() - start_time).total_seconds()
        
        answer = rag_result["answer"]
        chunks = rag_result.get("chunks", [])
        
        # B. Validate
        # Note: In a real benchmark, we'd compare against 'gold' using BERTScore/Rouge
        # Our current validator compares Answer vs Context (Faithfulness)
        # We can extend it here to compare Answer vs Gold.
        
        val_result = await validator.validate_answer(
            query,
            answer,
            chunks,
            user_id="benchmark_runner",
            subject=subject
        )
        
        # Calculate Reference metrics (Answer vs Gold)
        from backend.core.evaluation.metrics import calculate_bert_score
        ref_score = calculate_bert_score(answer, gold)
        
        print(f"   ✅ Faithfulness: {val_result.faithfulness_score:.2f}")
        print(f"   ✅ BERTScore (vs Gold): {ref_score:.2f}")
        print(f"   ⏱️ Latency: {duration:.2f}s")
        
        results.append({
            "question": query,
            "faithfulness": val_result.faithfulness_score,
            "hallucination": val_result.hallucination_rate,
            "bert_score_gold": ref_score,
            "latency": duration
        })

    # 4. Summary
    avg_faith = sum(r["faithfulness"] for r in results) / len(results)
    avg_bert = sum(r["bert_score_gold"] for r in results) / len(results)
    
    print("\n" + "="*40)
    print("📢 BENCHMARK SUMMARY")
    print("="*40)
    print(f"Total Tests: {len(results)}")
    print(f"Avg Faithfulness: {avg_faith:.2f}")
    print(f"Avg BERTScore (Acc): {avg_bert:.2f}")
    print("="*40)

if __name__ == "__main__":
    # Windows SelectorEventLoop fix logic if needed
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    asyncio.run(run_benchmark())
