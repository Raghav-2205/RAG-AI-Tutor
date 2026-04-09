# 🚀 RAG LMS - Correct Access URLs

## ✅ **Working Configuration**

Your backend is running on **port 8003** (as shown in your terminal output):
```
Server URL: http://127.0.0.1:8003
```

## 🌐 **Correct URLs to Access LMS**

### **Main LMS Page**
```
http://127.0.0.1:8003/views/lms.html?allow_student=1&page=classes
```

### **Dashboard**
```
http://127.0.0.1:8003/views/dashboard.html
```

### **Analytics**
```
http://127.0.0.1:8003/views/analytics.html
```

### **Login Page**
```
http://127.0.0.1:8003/views/login.html
```

## 🔧 **Why This Works**

The frontend configuration is smart:
- `config.js` automatically uses `${window.location.origin}/api`
- When you access `http://127.0.0.1:8003`, it will use `http://127.0.0.1:8003/api`
- No hardcoded URLs in the LMS system

## ❌ **Incorrect URL (What you were using)**
```
http://127.0.0.1:8000/views/lms.html  ← WRONG PORT
```

## ✅ **Correct URL (What you should use)**
```
http://127.0.0.1:8003/views/lms.html?allow_student=1&page=classes  ← CORRECT PORT
```

## 🎯 **Quick Test**

1. Open your browser
2. Go to: `http://127.0.0.1:8003/views/lms.html?allow_student=1&page=classes`
3. The LMS should load properly with full functionality!

## 📝 **Note**

The port 8003 is configured in your `run.py` file:
```python
port = int(os.getenv("RUN_PORT", "8003"))
```

If you want to change it to 8000, you can:
1. Set environment variable: `RUN_PORT=8000`
2. Or modify the `run.py` file directly

But it's easier to just use the correct port 8003! 🚀
