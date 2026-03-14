import asyncio
import logging
from backend.evaluation.evaluation_runner import EvaluationRunner

# Configure logging
logging.basicConfig(level=logging.INFO)

async def test_runner():
    print("🚀 Starting Evaluation Runner Test...")
    try:
        runner = EvaluationRunner(user_id="test_user")
        
        # Test Initialize
        print("Initializing...")
        await runner.initialize()
        
        # Test Load Data
        print("Loading data...")
        data = runner.load_evaluation_dataset()
        print(f"Loaded {len(data)} questions.")
        
        if data:
            item = data[0]
            print(f"Testing single evaluation for: {item['question']}")
            
            result = await runner.evaluate_single(
                question=item['question'],
                gold_answer=item['gold_answer'],
                gold_chunk_id=item.get('gold_chunk_id'),
                subject=item.get('subject', 'general')
            )
            
            print("Evaluation Result:", result)
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_runner())
