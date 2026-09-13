#!/usr/bin/env python3
"""Quick setup and validation script for the research system."""

import sys
import subprocess
import os
from pathlib import Path


def run_command(cmd, description):
    """Run a command and report results."""
    print(f"\n{'='*70}")
    print(f"📋 {description}")
    print(f"{'='*70}")
    print(f"$ {cmd}\n")
    
    result = subprocess.run(cmd, shell=True)
    return result.returncode == 0


def check_environment():
    """Check if environment is set up correctly."""
    print("\n" + "="*70)
    print("🔍 ENVIRONMENT CHECK")
    print("="*70)
    
    checks = []
    
    # Check Python version
    print(f"\n✓ Python version: {sys.version.split()[0]}")
    if sys.version_info >= (3, 9):
        print("  ✅ Python 3.9+ required")
        checks.append(True)
    else:
        print("  ❌ Python 3.9+ required (upgrade needed)")
        checks.append(False)
    
    # Check if in research_system directory
    cwd = Path.cwd()
    if cwd.name == "research_system":
        print(f"\n✓ Working directory: {cwd}")
        print("  ✅ Correct directory")
        checks.append(True)
    else:
        print(f"\n✗ Working directory: {cwd}")
        print("  ❌ Should run from research_system directory")
        checks.append(False)
    
    # Check requirements.txt exists
    if Path("requirements.txt").exists():
        print(f"\n✓ requirements.txt found")
        print("  ✅ Dependencies file present")
        checks.append(True)
    else:
        print(f"\n✗ requirements.txt not found")
        print("  ❌ Missing dependencies file")
        checks.append(False)
    
    # Check src directory exists
    if Path("src").exists():
        print(f"\n✓ src/ directory found")
        print("  ✅ Source code directory present")
        checks.append(True)
    else:
        print(f"\n✗ src/ directory not found")
        print("  ❌ Missing source code")
        checks.append(False)
    
    return all(checks)


def install_dependencies():
    """Install Python dependencies."""
    return run_command(
        "pip install -r requirements.txt",
        "Installing dependencies from requirements.txt"
    )


def run_tests():
    """Run the test suite."""
    return run_command(
        "pytest tests/ -v --tb=short",
        "Running unit tests"
    )


def validate_imports():
    """Validate that core modules can be imported."""
    print("\n" + "="*70)
    print("🧪 IMPORT VALIDATION")
    print("="*70)
    
    modules = [
        ("src.models", "Data models"),
        ("src.database", "Database layer"),
        ("src.config", "Configuration"),
        ("src.agents", "Agent framework"),
        ("src.services", "Business logic"),
        ("src.main", "REST API"),
    ]
    
    all_ok = True
    
    for module, description in modules:
        try:
            __import__(module)
            print(f"✅ {module:20} - {description}")
        except Exception as e:
            print(f"❌ {module:20} - {description}")
            print(f"   Error: {str(e)[:60]}")
            all_ok = False
    
    return all_ok


def show_next_steps():
    """Show next steps after successful setup."""
    print("\n" + "="*70)
    print("🚀 NEXT STEPS")
    print("="*70)
    
    print("""
1. Start the development server:
   $ python run.py
   
   The API will be available at:
   - REST API: http://localhost:8000
   - Interactive Docs: http://localhost:8000/docs
   - Health Check: http://localhost:8000/health

2. In another terminal, test the API:
   $ curl http://localhost:8000/api/v1/system/info

3. Create a project:
   $ curl -X POST http://localhost:8000/api/v1/projects?tenant_id=TEN-001 \\
     -H "Content-Type: application/json" \\
     -d '{
       "name": "Test Project",
       "description": "Testing the system",
       "max_budget_usd": 100.0
     }'

4. Review the documentation:
   - README.md - Overview and quick start
   - ARCHITECTURE.md - Design patterns
   - IMPLEMENTATION_GUIDE.md - Implementation roadmap
   - QUICK_START.md - Detailed setup instructions
""")


def main():
    """Main setup routine."""
    print("\n" + "🔬 "*20)
    print("MULTI-AGENT RESEARCH SYSTEM - QUICK SETUP")
    print("🔬 "*20)
    
    # Step 1: Check environment
    if not check_environment():
        print("\n❌ Environment check failed. Please fix issues above.")
        sys.exit(1)
    
    # Step 2: Install dependencies
    print("\n" + "="*70)
    print("📦 DEPENDENCY INSTALLATION")
    print("="*70)
    
    response = input("\nInstall dependencies? (y/n): ").lower()
    if response == "y":
        if not install_dependencies():
            print("\n❌ Dependency installation failed")
            sys.exit(1)
    else:
        print("⏭️  Skipped dependency installation")
    
    # Step 3: Validate imports
    print("\nValidating imports...")
    if not validate_imports():
        print("\n⚠️  Some imports failed. Install dependencies first:")
        print("   $ pip install -r requirements.txt")
        sys.exit(1)
    
    # Step 4: Run tests (optional)
    print("\n" + "="*70)
    print("🧪 TESTING")
    print("="*70)
    
    response = input("\nRun unit tests? (y/n): ").lower()
    if response == "y":
        if not run_tests():
            print("\n⚠️  Some tests failed (this is OK for first run)")
        else:
            print("\n✅ All tests passed!")
    else:
        print("⏭️  Skipped tests")
    
    # Step 5: Show next steps
    show_next_steps()
    
    print("\n" + "="*70)
    print("✨ SETUP COMPLETE!")
    print("="*70)
    print("\n🎉 You're ready to start the research system!\n")


if __name__ == "__main__":
    main()
