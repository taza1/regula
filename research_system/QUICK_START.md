# Quick Start Guide - Running the Research System

## Option 1: Local Development (Fastest ⚡)

### Prerequisites
- Python 3.12+
- Git (already installed)
- pip

### Step 1: Navigate to the project
```bash
cd research_system
```

### Step 2: Install dependencies
```bash
pip install -r requirements.txt
```

This installs:
- FastAPI, Uvicorn (REST API)
- Pydantic (data validation)
- Azure SDKs (Cosmos DB, Blob Storage, etc.)
- OpenAI SDK (LLM integration)
- pytest (testing)

### Step 3: Configure environment
```bash
# Copy the example configuration
cp .env.example .env

# Edit .env with your settings
# For local testing, most values can be placeholders
```

**Minimal .env for testing:**
```
API_HOST=0.0.0.0
API_PORT=8000
OPENAI_API_VERSION=2023-12-01-preview
OPENAI_MODEL=gpt-4-turbo
```

### Step 4: Run the development server
```bash
python run.py
```

You should see:
```
======================================================================
Multi-Agent Research System - Starting
======================================================================
API Version: 1.0
Host: 0.0.0.0
Port: 8000
Documentation: http://0.0.0.0:8000/docs
======================================================================
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### Step 5: Access the API
- **API Documentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health
- **System Info**: http://localhost:8000/api/v1/system/info

### Step 6: Test with curl or browser
```bash
# Check health
curl http://localhost:8000/health

# Get system info
curl http://localhost:8000/api/v1/system/info

# Create a project (requires JSON body)
curl -X POST http://localhost:8000/api/v1/projects?tenant_id=TEN-001 \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Research Project",
    "description": "Testing the system",
    "max_budget_usd": 100.0
  }'
```

### Step 7: Run tests
```bash
pytest tests/ -v
```

---

## Option 2: Docker Local Development

### Step 1: Build the image
```bash
cd research_system
docker build -t research-system:latest .
```

### Step 2: Run the container
```bash
docker run -p 8000:8000 \
  -e API_HOST=0.0.0.0 \
  -e API_PORT=8000 \
  -e OPENAI_MODEL=gpt-4-turbo \
  research-system:latest
```

The API is now available at http://localhost:8000

---

## Option 3: Full Azure Deployment (Production)

### Step 1: Deploy Azure resources
```bash
# Install Azure CLI
# https://docs.microsoft.com/en-us/cli/azure/install-azure-cli

# Login to Azure
az login

# Create resource group
az group create \
  --name research-rg \
  --location eastus

# Deploy resources (requires Bicep templates)
# We'll create these in Phase 1
az deployment group create \
  --resource-group research-rg \
  --template-file infra/main.bicep
```

### Step 2: Configure production .env
Get Azure service credentials:
```bash
# Cosmos DB endpoint
az cosmosdb show --resource-group research-rg --name research-cosmos \
  --query documentEndpoint

# Storage account key
az storage account keys list --resource-group research-rg \
  --account-name researchstorage --query [0].value

# AI Search key
az search admin-key show --resource-group research-rg \
  --service-name research-search --query primaryKey
```

### Step 3: Deploy to Azure Container Instances or App Service
```bash
# Push image to Azure Container Registry
az acr build --registry <registry-name> \
  --image research-system:latest .

# Deploy to Container Instances
az container create \
  --resource-group research-rg \
  --name research-system \
  --image <registry-name>.azurecr.io/research-system:latest \
  --ports 8000 \
  --environment-variables-from-file env.list
```

---

## Common Issues & Solutions

### Issue 1: "ModuleNotFoundError: No module named 'src'"
**Solution**: Make sure you're running from the `research_system` directory
```bash
cd research_system
python run.py
```

### Issue 2: "Port 8000 already in use"
**Solution**: Use a different port
```bash
# Edit .env and change API_PORT to 8001
# Or kill the process using port 8000
# On Windows: netstat -ano | findstr :8000
# On Mac/Linux: lsof -i :8000
```

### Issue 3: "Cannot import azure.cosmos"
**Solution**: Reinstall dependencies
```bash
pip install --upgrade -r requirements.txt
```

### Issue 4: "OpenAI API key not found"
**Solution**: Set in environment
```bash
export OPENAI_API_KEY=sk-...
python run.py
```

---

## Testing the API

### 1. Using the Interactive Docs
- Go to http://localhost:8000/docs
- Click on any endpoint
- Click "Try it out"
- Enter parameters
- Click "Execute"

### 2. Using curl
```bash
# Create a project
curl -X POST http://localhost:8000/api/v1/projects?tenant_id=TEN-001 \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Climate Research",
    "description": "Global climate studies",
    "max_budget_usd": 100.0
  }'

# Create a research run
curl -X POST http://localhost:8000/api/v1/projects/PRJ-001/runs?tenant_id=TEN-001 \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Climate Impact Study",
    "primary_question": "What is the impact of climate change?",
    "scope_description": "Focus on peer-reviewed studies from 2020-2024",
    "max_cost_usd": 50.0
  }'
```

### 3. Using Python
```python
import requests
import json

base_url = "http://localhost:8000"
tenant_id = "TEN-001"
project_id = "PRJ-001"

# Create project
response = requests.post(
    f"{base_url}/api/v1/projects?tenant_id={tenant_id}",
    json={
        "name": "Test Project",
        "max_budget_usd": 100.0
    }
)
print(json.dumps(response.json(), indent=2))
```

---

## Next Steps After Getting It Running

1. **Review the API documentation**: http://localhost:8000/docs
2. **Explore the codebase**:
   - Start with `src/models.py` to understand data structures
   - Then look at `src/services.py` for business logic
   - Finally check `src/main.py` for API endpoints

3. **Read the architecture guide**:
   ```bash
   cat research_system/ARCHITECTURE.md
   ```

4. **Follow the implementation guide for Phase 1**:
   ```bash
   cat research_system/IMPLEMENTATION_GUIDE.md
   ```

5. **Run the tests**:
   ```bash
   pytest research_system/tests/ -v --cov=research_system/src
   ```

---

## Environment Variables Reference

### Essential for Running
```
API_HOST=0.0.0.0
API_PORT=8000
OPENAI_MODEL=gpt-4-turbo
OPENAI_TEMPERATURE=0.0
```

### For Azure Integration (optional for local testing)
```
TENANT_ID=your-tenant-id
COSMOS_ENDPOINT=https://xxx.documents.azure.com
BLOB_STORAGE_ACCOUNT=researchstorage
SEARCH_SERVICE_NAME=research-search
SERVICE_BUS_NAMESPACE=research-bus
```

See `.env.example` for all available options.

---

## Troubleshooting Commands

```bash
# Check Python version
python --version  # Should be 3.9+

# Check dependencies
pip list | grep -E "fastapi|pydantic|azure"

# Test import
python -c "import src.models; print('✓ Models imported successfully')"

# Run with verbose logging
python run.py --reload  # or edit run.py and set log_level="debug"

# Check if port is accessible
curl http://localhost:8000/health

# View logs in Docker
docker logs -f <container-id>
```

---

## Quick Commands Reference

| Task | Command |
|------|---------|
| Install dependencies | `pip install -r requirements.txt` |
| Run dev server | `python run.py` |
| Run tests | `pytest tests/ -v` |
| Build Docker image | `docker build -t research-system:latest .` |
| Run Docker locally | `docker run -p 8000:8000 research-system:latest` |
| View API docs | Open http://localhost:8000/docs |
| Check health | `curl http://localhost:8000/health` |

---

**You are now ready to run the system!** 🚀

Choose your approach above and follow the steps. Most people start with **Option 1 (Local Development)** for quick testing.
