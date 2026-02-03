print('🧠 Skipping model download - Using lightweight demo')
print('✅ Backend will use simple embeddings')
print('📁 Created placeholder models')

# Create directories
import os
os.makedirs('models/embedding', exist_ok=True)
os.makedirs('models/llm', exist_ok=True)

# Placeholder files
open('models/embedding/model.bin', 'w').write('Ready')
open('models/llm/model.bin', 'w').write('Ready')

print('✅ Setup complete! Start backend now.')
