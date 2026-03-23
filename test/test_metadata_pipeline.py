import asyncio
import sys
from pathlib import Path
from _bootstrap import ensure_project_root

ensure_project_root()

from backend.rag_tutor import answer_query_with_rag

async def test():
    print('Testing query...')
    res = await answer_query_with_rag(
        user_id='global',
        query='integral calculus',
        subject='general'
    )
    print('Response Check:')
    if res.get('chunks'):
        for c in res.get('chunks'):
            print(f'Chunk metadata:')
            meta = c.get('metadata', {})
            print(f'  - Source: {meta.get("source")}')
            print(f'  - Page: {meta.get("page")}')
            print(f'  - Type: {meta.get("type")}')
            print(f'  - Chunk ID: {meta.get("chunk_id")}')
            print(f'  - Doc ID: {meta.get("doc_id")}')
            print('---')
    else:
        print('No chunks returned.')

if __name__ == '__main__':
    asyncio.run(test())
