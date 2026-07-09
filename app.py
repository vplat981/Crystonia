from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import os
import asyncpg
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI(title="Crystonia Bank API", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supabase configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in environment variables")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Pydantic models
class TransactionRequest(BaseModel):
    user_id: str
    amount: float = Field(gt=0, description="Amount must be greater than 0")

class TransactionResponse(BaseModel):
    id: int
    user_id: str
    type: str
    amount: float
    description: Optional[str]
    created_at: datetime

class BalanceResponse(BaseModel):
    user_id: str
    amount: float
    updated_at: datetime

class BankResponse(BaseModel):
    success: bool
    message: str
    balance: Optional[float] = None
    transaction: Optional[TransactionResponse] = None

# Helper functions
async def get_user_balance(user_id: str) -> float:
    """Get current balance for a user"""
    try:
        response = supabase.table("balances").select("amount").eq("user_id", user_id).execute()
        if response.data and len(response.data) > 0:
            return float(response.data[0]["amount"])
        return 0.0
    except Exception as e:
        print(f"Error getting balance: {e}")
        raise HTTPException(status_code=500, detail="Failed to get balance")

async def update_user_balance(user_id: str, new_amount: float) -> bool:
    """Update user balance"""
    try:
        # Check if user exists
        check = supabase.table("balances").select("user_id").eq("user_id", user_id).execute()
        
        if not check.data or len(check.data) == 0:
            # Create new balance record
            supabase.table("balances").insert({
                "user_id": user_id,
                "amount": new_amount
            }).execute()
        else:
            # Update existing balance
            supabase.table("balances").update({
                "amount": new_amount,
                "updated_at": datetime.utcnow().isoformat()
            }).eq("user_id", user_id).execute()
        return True
    except Exception as e:
        print(f"Error updating balance: {e}")
        return False

async def add_transaction(user_id: str, transaction_type: str, amount: float, description: Optional[str] = None):
    """Add a transaction record"""
    try:
        if not description:
            description = f"{transaction_type.capitalize()} of {amount:.2f} CRY"
            
        response = supabase.table("transactions").insert({
            "user_id": user_id,
            "type": transaction_type,
            "amount": amount,
            "description": description
        }).execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error adding transaction: {e}")
        return None

# API Endpoints

@app.get("/")
async def root():
    return {
        "name": "Crystonia Bank API",
        "version": "1.0.0",
        "status": "operational",
        "endpoints": {
            "/balance/{user_id}": "Get user balance",
            "/transactions/{user_id}": "Get user transactions",
            "/deposit": "Deposit funds",
            "/withdraw": "Withdraw funds"
        }
    }

@app.get("/balance/{user_id}", response_model=BalanceResponse)
async def get_balance(user_id: str):
    """Get current balance for a user"""
    try:
        response = supabase.table("balances").select("*").eq("user_id", user_id).execute()
        
        if not response.data or len(response.data) == 0:
            # Create balance if it doesn't exist
            supabase.table("balances").insert({
                "user_id": user_id,
                "amount": 0
            }).execute()
            
            response = supabase.table("balances").select("*").eq("user_id", user_id).execute()
            
            if not response.data or len(response.data) == 0:
                raise HTTPException(status_code=404, detail="Could not create or find user balance")
        
        balance_data = response.data[0]
        return BalanceResponse(
            user_id=balance_data["user_id"],
            amount=float(balance_data["amount"]),
            updated_at=datetime.fromisoformat(balance_data["updated_at"].replace('Z', '+00:00'))
        )
    except Exception as e:
        print(f"Error in get_balance: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/transactions/{user_id}", response_model=List[TransactionResponse])
async def get_transactions(user_id: str, limit: int = 20):
    """Get recent transactions for a user"""
    try:
        response = supabase.table("transactions") \
            .select("*") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()
        
        transactions = []
        if response.data:
            for t in response.data:
                transactions.append(TransactionResponse(
                    id=t["id"],
                    user_id=t["user_id"],
                    type=t["type"],
                    amount=float(t["amount"]),
                    description=t.get("description"),
                    created_at=datetime.fromisoformat(t["created_at"].replace('Z', '+00:00'))
                ))
        return transactions
    except Exception as e:
        print(f"Error in get_transactions: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/deposit", response_model=BankResponse)
async def deposit(transaction: TransactionRequest):
    """Deposit funds into account"""
    try:
        # Get current balance
        current_balance = await get_user_balance(transaction.user_id)
        new_balance = current_balance + transaction.amount
        
        # Update balance
        success = await update_user_balance(transaction.user_id, new_balance)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update balance")
        
        # Add transaction record
        transaction_record = await add_transaction(
            transaction.user_id, 
            "deposit", 
            transaction.amount,
            f"Deposit of {transaction.amount:.2f} CRY"
        )
        
        return BankResponse(
            success=True,
            message=f"Successfully deposited {transaction.amount:.2f} CRY",
            balance=new_balance,
            transaction=TransactionResponse(
                id=transaction_record["id"],
                user_id=transaction_record["user_id"],
                type=transaction_record["type"],
                amount=float(transaction_record["amount"]),
                description=transaction_record.get("description"),
                created_at=datetime.fromisoformat(transaction_record["created_at"].replace('Z', '+00:00'))
            ) if transaction_record else None
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in deposit: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during deposit")

@app.post("/withdraw", response_model=BankResponse)
async def withdraw(transaction: TransactionRequest):
    """Withdraw funds from account"""
    try:
        # Get current balance
        current_balance = await get_user_balance(transaction.user_id)
        
        # Check sufficient funds
        if current_balance < transaction.amount:
            raise HTTPException(
                status_code=400, 
                detail=f"Insufficient funds. Current balance: {current_balance:.2f} CRY"
            )
        
        new_balance = current_balance - transaction.amount
        
        # Update balance
        success = await update_user_balance(transaction.user_id, new_balance)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update balance")
        
        # Add transaction record
        transaction_record = await add_transaction(
            transaction.user_id, 
            "withdraw", 
            transaction.amount,
            f"Withdrawal of {transaction.amount:.2f} CRY"
        )
        
        return BankResponse(
            success=True,
            message=f"Successfully withdrew {transaction.amount:.2f} CRY",
            balance=new_balance,
            transaction=TransactionResponse(
                id=transaction_record["id"],
                user_id=transaction_record["user_id"],
                type=transaction_record["type"],
                amount=float(transaction_record["amount"]),
                description=transaction_record.get("description"),
                created_at=datetime.fromisoformat(transaction_record["created_at"].replace('Z', '+00:00'))
            ) if transaction_record else None
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in withdraw: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during withdrawal")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Test Supabase connection
        supabase.table("balances").select("count").limit(1).execute()
        return {"status": "healthy", "supabase": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "supabase": "disconnected", "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
