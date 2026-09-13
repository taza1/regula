# 🚀 RUNNING THE RESEARCH SYSTEM - STEP-BY-STEP

## ⚡ TL;DR (Fastest Way - 3 minutes)

```bash
# 1. Go to the project directory
cd research_system

# 2. Install dependencies (first time only)
pip install -r requirements.txt

# 3. Run the server
python run.py

# 4. Open in browser
# http://localhost:8000/docs
```

That's it! You'll see the interactive API documentation.

---

## 📋 Complete Setup Guide

### Step 1️⃣: Prerequisites Check

Make sure you have:
- ✅ Python 3.9 or higher
- ✅ pip (Python package manager)
- ✅ Git (already have this)

**Check your setup:**
```bash
python --version
pip --version
```

**If you see version numbers, you're good to go!**

---

### Step 2️⃣: Navigate to the Project

```bash
# From the repo root, go to research_system directory
cd research_system

# Verify you're in the right place
ls -la src/
# Should show: __init__.py, agents.py, config.py, database.py, main.py, models.py, services.py
```

---

### Step 3️⃣: Install Dependencies

**First time only:**
```bash
pip install -r requirements.txt
```

This installs:
- 📦 FastAPI (REST framework)
- 📦 Pydantic (data validation)
- 📦 Azure SDKs (cloud services)
- 📦 OpenAI SDK (LLM integration)
- 📦 pytest (testing)
- ...and more

**Expected output:**
```
Successfully installed fastapi-0.104.1 uvicorn-0.24.0 pydantic-2.4.2 ...
```

---

### Step 4️⃣: Run the Development Server

**Option A: Simple Start**
```bash
python run.py
```

**Option B: With Auto-reload (recommended for development)**
```bash
python -m uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

**Option C: Docker**
```bash
docker build -t research-system:latest .
docker run -p 8000:8000 research-system:latest
```

**Expected output:**
```
======================================================================
Multi-Agent Research System - Starting
======================================================================
API Version: 1.0
Host: 0.0.0.0
Port: 8000
Documentation: http://0.0.0.0:8000/docs
======================================================================
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started server process [12345]
INFO:     Application startup complete [Lifespan]
```

✅ **Server is now running!**

---

### Step 5️⃣: Access the API

#### 🌐 Interactive Documentation (Best Way)
Open your browser and go to:
```
http://localhost:8000/docs
```

You'll see:
- All available endpoints
- Request/response schemas
- "Try it out" buttons to test endpoints

#### 📊 System Info
```
http://localhost:8000/api/v1/system/info
```

#### 💚 Health Check
```
http://localhost:8000/health
```

---

## 🧪 Testing the System

### Method 1: Interactive Docs (Easiest)
1. Go to http://localhost:8000/docs
2. Click on any endpoint (e.g., `POST /api/v1/projects`)
3. Click "Try it out"
4. Fill in parameters
5. Click "Execute"
6. See the response

### Method 2: Command Line (curl)

```bash
# Test health
curl http://localhost:8000/health

# Get system info
curl http://localhost:8000/api/v1/system/info

# Create a project
curl -X POST "http://localhost:8000/api/v1/projects?tenant_id=TEN-001" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Climate Research",
    "description": "Global climate studies",
    "max_budget_usd": 100.0
  }'

# Create a research run
curl -X POST "http://localhost:8000/api/v1/projects/PRJ-001/runs?tenant_id=TEN-001" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Climate Impact Study",
    "primary_question": "What is the impact of climate change?",
    "scope_description": "Focus on peer-reviewed studies",
    "max_cost_usd": 50.0
  }'
```

### Method 3: Python Script

```python
import requests

# Start local server first: python run.py

base_url = "http://localhost:8000"

# Test health
response = requests.get(f"{base_url}/health")
print("Health:", response.json())

# Create project
response = requests.post(
    f"{base_url}/api/v1/projects?tenant_id=TEN-001",
    json={
        "name": "Test Project",
        "max_budget_usd": 100.0
    }
)
print("Project created:", response.json())
```

---

## 🧬 Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=src

# Run specific test file
pytest tests/test_models.py -v

# Run specific test
pytest tests/test_models.py::TestModels::test_run_record_creation -v
```

**Expected output:**
```
tests/test_models.py::TestModels::test_research_request_creation PASSED
tests/test_models.py::TestModels::test_run_record_creation PASSED
tests/test_models.py::TestModels::test_evidence_record_creation PASSED
...
============== 20 passed in 0.45s ==============
```

---

## 🛠️ Troubleshooting

### Problem: "ModuleNotFoundError: No module named 'pydantic'"
**Solution:** Install dependencies
```bash
pip install -r requirements.txt
```

### Problem: "Port 8000 already in use"
**Solution:** Use a different port
```bash
python -m uvicorn src.main:app --port 8001
# Then access at http://localhost:8001/docs
```

### Problem: "No such file or directory: 'run.py'"
**Solution:** Make sure you're in the `research_system` directory
```bash
cd research_system
python run.py
```

### Problem: Import errors when running
**Solution:** Make sure current directory is in Python path
```bash
# Instead of: python src/main.py
# Do this: python run.py

# Or: python -m uvicorn src.main:app
```

---

## 📚 What to Do Next

### 1. Explore the API
Go to http://localhost:8000/docs and try each endpoint:
- ✅ Create a project
- ✅ Create a research run
- ✅ Understand the data flow

### 2. Read the Documentation
- **ARCHITECTURE.md** - How the system is designed
- **IMPLEMENTATION_GUIDE.md** - Next phases of development
- **README.md** - Overview and features

### 3. Study the Code
```
research_system/src/
├── models.py       → Data structures
├── database.py     → Cosmos DB models
├── config.py       → Configuration
├── agents.py       → Multi-agent framework
├── services.py     → Business logic
└── main.py         → REST API
```

Start with `models.py` to understand the data flow.

### 4. Run the Tests
```bash
pytest tests/ -v
```

### 5. Follow the Implementation Guide
Read `IMPLEMENTATION_GUIDE.md` to understand Phase 1-6:
- Phase 1: Infrastructure Setup
- Phase 2: Agent Implementation
- Phase 3: Search & Retrieval
- Phase 4: Review Pipeline
- Phase 5: Release Workflow
- Phase 6: Operations & Testing

---

## 🎯 Common Tasks

### Check if server is running
```bash
curl http://localhost:8000/health
# Should return: {"status":"healthy","version":"1.0"}
```

### View API documentation
```
http://localhost:8000/docs
```

### Create a test project
```bash
curl -X POST "http://localhost:8000/api/v1/projects?tenant_id=TEN-001" \
  -H "Content-Type: application/json" \
  -d '{"name":"Test","max_budget_usd":100}'
```

### View real-time logs
Keep the server running and watch output in terminal.

### Stop the server
```
Press CTRL+C in the terminal
```

---

## 📦 What Gets Installed

When you run `pip install -r requirements.txt`, you get:

**Web Framework:**
- FastAPI 0.104.1 - REST API framework
- Uvicorn 0.24.0 - ASGI server

**Data Validation:**
- Pydantic 2.4.2 - Data validation
- Pydantic Settings 2.0.3 - Configuration management

**Azure Integration:**
- azure-cosmos 4.5.1 - Cosmos DB
- azure-storage-blob 12.18.3 - Blob Storage
- azure-service-bus 7.11.0 - Service Bus
- azure-search-documents - AI Search
- azure-identity 1.14.0 - Authentication

**AI/ML:**
- openai 1.3.5 - OpenAI API
- langchain 0.0.338 - LLM framework

**Parsing:**
- trafilatura 1.6.3 - Web content extraction
- beautifulsoup4 4.12.2 - HTML parsing
- pymupdf 1.23.8 - PDF extraction

**Testing:**
- pytest 7.4.3
- pytest-asyncio 0.21.1
- pytest-cov 4.1.0

**Monitoring:**
- opentelemetry-api 1.20.0 - Tracing
- opentelemetry-exporter-azure-monitor - Azure monitoring

---

## ✅ Success Checklist

- [ ] Python 3.9+ installed
- [ ] In `research_system` directory
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] Server running (`python run.py`)
- [ ] API docs accessible (http://localhost:8000/docs)
- [ ] Can create a project (via API docs or curl)
- [ ] Tests pass (`pytest tests/ -v`)
- [ ] Understand project structure (looked at src/ files)
- [ ] Read ARCHITECTURE.md
- [ ] Ready to implement Phase 1!

---

## 🚀 You're Ready!

The research system is running. Now:
1. Explore the API at http://localhost:8000/docs
2. Create a test project
3. Study the code
4. Read the documentation
5. Follow the implementation guide for next phases

**Questions?** Check the documentation files or review the code comments.

Happy researching! 🔬
