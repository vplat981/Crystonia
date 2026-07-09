from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timedelta
import os
import hashlib
import secrets
from supabase import create_client, Client
from dotenv import load_dotenv
import jwt
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Load environment variables
load_dotenv()

app = FastAPI(title="Crystonia Bank API", version="1.0.0")

# Security
security = HTTPBearer()
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

# ============= MODELS (defined first) =============
class UserSignup(BaseModel):
    username: str
    email: str
    password: str
    full_name: Optional[str] = None

class UserLogin(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user_id: str
    username: str

class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    full_name: Optional[str]
    balance: float
    created_at: datetime

class TransactionRequest(BaseModel):
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

# ============= HELPER FUNCTIONS =============
def hash_password(password: str) -> str:
    """Hash password using SHA256"""
    salt = secrets.token_hex(16)
    return salt + ":" + hashlib.sha256((salt + password).encode()).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    """Verify password against hash"""
    salt, hash_value = hashed.split(":")
    return hash_value == hashlib.sha256((salt + password).encode()).hexdigest()

def create_access_token(user_id: str, username: str) -> str:
    """Create JWT token"""
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "username": username,
        "exp": expire
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str) -> dict:
    """Verify JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get current user from token"""
    payload = verify_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    # Get user from database
    response = supabase.table("users").select("*").eq("id", user_id).execute()
    if not response.data or len(response.data) == 0:
        raise HTTPException(status_code=401, detail="User not found")
    
    return response.data[0]

async def get_user_balance(user_id: str) -> float:
    """Get current balance for a user"""
    try:
        response = supabase.table("balances").select("amount").eq("user_id", user_id).execute()
        if response.data and len(response.data) > 0:
            return float(response.data[0]["amount"])
        # Create balance if it doesn't exist
        supabase.table("balances").insert({
            "user_id": user_id,
            "amount": 0
        }).execute()
        return 0.0
    except Exception as e:
        print(f"Error getting balance: {e}")
        return 0.0

async def update_user_balance(user_id: str, new_amount: float) -> bool:
    """Update user balance"""
    try:
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

# ============= ROOT ENDPOINT - SERVES HTML =============
@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the Crystonia Bank frontend"""
    try:
        with open("index.html", "r") as f:
            return f.read()
    except FileNotFoundError:
        return """
        <html>
            <head><title>Crystonia Bank</title></head>
            <body>
                <h1>✦ Crystonia Bank</h1>
                <p>API is running. Please ensure index.html exists.</p>
                <p><a href="/api">View API Documentation</a></p>
            </body>
        </html>
        """

# ============= API INFO =============
@app.get("/api")
async def api_info():
    """API information"""
    return {
        "name": "Crystonia Bank API",
        "version": "1.0.0",
        "status": "operational",
        "endpoints": {
            "/": "HTML Frontend",
            "/api": "This API info",
            "/auth/signup": "Register new user (POST)",
            "/auth/login": "Login user (POST)",
            "/auth/me": "Get current user info (GET)",
            "/balance": "Get user balance (GET)",
            "/transactions": "Get transaction history (GET)",
            "/deposit": "Deposit funds (POST)",
            "/withdraw": "Withdraw funds (POST)",
            "/health": "Health check (GET)"
        }
    }

# ============= HEALTH CHECK =============
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        supabase.table("users").select("count").limit(1).execute()
        return {"status": "healthy", "supabase": "connected", "timestamp": datetime.utcnow().isoformat()}
    except Exception as e:
        return {"status": "unhealthy", "supabase": "disconnected", "error": str(e)}

# ============= AUTH ENDPOINTS =============
@app.post("/auth/signup", response_model=TokenResponse)
async def signup(user: UserSignup):
    """Register a new user"""
    try:
        # Check if user exists
        existing = supabase.table("users").select("email").eq("email", user.email).execute()
        if existing.data and len(existing.data) > 0:
            raise HTTPException(status_code=400, detail="Email already registered")
        
        # Create user
        hashed_password = hash_password(user.password)
        user_data = {
            "username": user.username,
            "email": user.email,
            "password_hash": hashed_password,
            "full_name": user.full_name,
            "created_at": datetime.utcnow().isoformat()
        }
        
        response = supabase.table("users").insert(user_data).execute()
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=500, detail="Failed to create user")
        
        new_user = response.data[0]
        user_id = new_user["id"]
        
        # Create initial balance
        supabase.table("balances").insert({
            "user_id": user_id,
            "amount": 1000.00  # Welcome bonus!
        }).execute()
        
        # Create welcome transaction
        await add_transaction(
            user_id,
            "deposit",
            1000.00,
            "Welcome bonus! 🎉"
        )
        
        # Generate token
        token = create_access_token(user_id, user.username)
        
        return TokenResponse(
            access_token=token,
            token_type="bearer",
            user_id=user_id,
            username=user.username
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in signup: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/auth/login", response_model=TokenResponse)
async def login(user: UserLogin):
    """Login existing user"""
    try:
        # Get user
        response = supabase.table("users").select("*").eq("email", user.email).execute()
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        db_user = response.data[0]
        
        # Verify password
        if not verify_password(user.password, db_user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        # Generate token
        token = create_access_token(db_user["id"], db_user["username"])
        
        return TokenResponse(
            access_token=token,
            token_type="bearer",
            user_id=db_user["id"],
            username=db_user["username"]
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in login: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    """Get current user info"""
    try:
        balance = await get_user_balance(current_user["id"])
        return UserResponse(
            id=current_user["id"],
            username=current_user["username"],
            email=current_user["email"],
            full_name=current_user.get("full_name"),
            balance=balance,
            created_at=datetime.fromisoformat(current_user["created_at"].replace('Z', '+00:00'))
        )
    except Exception as e:
        print(f"Error in get_me: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# ============= BANKING ENDPOINTS =============
@app.get("/balance", response_model=BalanceResponse)
async def get_balance(current_user: dict = Depends(get_current_user)):
    """Get current user's balance"""
    try:
        balance = await get_user_balance(current_user["id"])
        return BalanceResponse(
            user_id=current_user["id"],
            amount=balance,
            updated_at=datetime.utcnow()
        )
    except Exception as e:
        print(f"Error in get_balance: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/transactions", response_model=List[TransactionResponse])
async def get_transactions(limit: int = 20, current_user: dict = Depends(get_current_user)):
    """Get user's transaction history"""
    try:
        response = supabase.table("transactions") \
            .select("*") \
            .eq("user_id", current_user["id"]) \
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
async def deposit(transaction: TransactionRequest, current_user: dict = Depends(get_current_user)):
    """Deposit funds into account"""
    try:
        current_balance = await get_user_balance(current_user["id"])
        new_balance = current_balance + transaction.amount
        
        success = await update_user_balance(current_user["id"], new_balance)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update balance")
        
        transaction_record = await add_transaction(
            current_user["id"],
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
async def withdraw(transaction: TransactionRequest, current_user: dict = Depends(get_current_user)):
    """Withdraw funds from account"""
    try:
        current_balance = await get_user_balance(current_user["id"])
        
        if current_balance < transaction.amount:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient funds. Current balance: {current_balance:.2f} CRY"
            )
        
        new_balance = current_balance - transaction.amount
        
        success = await update_user_balance(current_user["id"], new_balance)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update balance")
        
        transaction_record = await add_transaction(
            current_user["id"],
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
