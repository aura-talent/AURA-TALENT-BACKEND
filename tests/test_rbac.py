import os
import sys
from unittest.mock import MagicMock

# Ensure backend package can be imported
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Mock the supabase proxy before importing app modules
from app import storage

# Create mocks for Supabase client
mock_supabase_client = MagicMock()
storage.supabase = mock_supabase_client

# Define mock database storage
mock_db = {
    "users": {}
}

# Mock the table builder behavior
def mock_table(table_name):
    mock_builder = MagicMock()
    
    def mock_upsert(data):
        row_id = data.get("id")
        mock_db[table_name][row_id] = data
        mock_exec = MagicMock()
        mock_exec.data = [data]
        return mock_exec
        
    def mock_select(select_str):
        mock_eq_builder = MagicMock()
        
        def mock_eq(field, value):
            mock_exec = MagicMock()
            results = []
            for row in mock_db[table_name].values():
                if row.get(field) == value:
                    results.append(row)
            mock_exec.data = results
            return mock_exec
            
        mock_eq_builder.eq = mock_eq
        return mock_eq_builder

    mock_builder.upsert = mock_upsert
    mock_builder.select = mock_select
    return mock_builder

mock_supabase_client.table = mock_table

from app.storage import save_user, get_user_role
from app.auth import verify_user_role
from fastapi import HTTPException

def run_tests():
    print("Starting RBAC verification tests with mocked Supabase...")

    try:
        # 1. Create a test candidate user
        print("Saving test candidate user...")
        save_user("test-candidate-id-123", "candidate@test.com", "Test Candidate", None, "candidate")
        
        # 2. Create a test employer user
        print("Saving test employer user...")
        save_user("test-employer-id-123", "employer@test.com", "Test Employer", None, "employer")
        
        # 3. Test roles in storage
        cand_role = get_user_role("test-candidate-id-123")
        emp_role = get_user_role("test-employer-id-123")
        print(f"Candidate role: {cand_role} (Expected: candidate)")
        print(f"Employer role: {emp_role} (Expected: employer)")
        
        assert cand_role == "candidate", "Role should be candidate"
        assert emp_role == "employer", "Role should be employer"
        
        # 4. Test verify_user_role - Success cases
        print("Testing authorization with correct role...")
        verify_user_role("test-candidate-id-123", ["candidate"])
        print("Candidate authorized for candidate-only action.")
        
        verify_user_role("test-candidate-id-123", ["candidate", "employer"])
        verify_user_role("test-employer-id-123", ["candidate", "employer"])
        print("Both roles authorized for shared actions.")
        
        # 5. Test verify_user_role - Failure case (Forbidden)
        print("Testing authorization block for incorrect role...")
        try:
            verify_user_role("test-employer-id-123", ["candidate"])
            print("Failure: Employer was allowed to perform candidate-only action.")
            sys.exit(1)
        except HTTPException as e:
            print(f"Successfully blocked: HTTP {e.status_code} - {e.detail}")
            assert e.status_code == 403, "Status code should be 403"
            
        # 6. Test verify_user_role - Default behavior (Anonymous/Non-existent)
        print("Testing anonymous/default role fallback...")
        verify_user_role("non-existent-user-id", ["candidate"])
        print("Non-existent user resolved to default 'candidate' role successfully.")
        
        try:
            verify_user_role("non-existent-user-id", ["employer"])
            print("Failure: Non-existent user was allowed to perform employer-only action.")
            sys.exit(1)
        except HTTPException as e:
            print(f"Successfully blocked: HTTP {e.status_code} - {e.detail}")
            assert e.status_code == 403, "Status code should be 403"

        print("ALL TESTS PASSED SUCCESSFULLY!")
    except Exception as e:
        print(f"Test runner encountered error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_tests()
