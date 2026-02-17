# MongoDB Atlas Setup Guide

Complete beginner guide to set up MongoDB Atlas for the Capstone Backend.

---

## Step 1: Create MongoDB Atlas Account

1. Go to [https://www.mongodb.com/cloud/atlas](https://www.mongodb.com/cloud/atlas)
2. Click **"Try Free"** or **"Start Free"**
3. Sign up with email or Google account
4. Verify your email if required

---

## Step 2: Create a New Cluster (Free Tier)

1. After login, click **"Build a Database"**
2. Choose **"M0 FREE"** (Shared, Free Forever)
3. Select your preferred cloud provider:
   - **AWS** (recommended)
   - Google Cloud
   - Azure
4. Choose a region closest to you (e.g., `Singapore` for Philippines)
5. Name your cluster (e.g., `CapstoneCluster`)
6. Click **"Create"**

> ⏳ Wait 1-3 minutes for cluster to be created

---

## Step 3: Create Database User

1. In the left sidebar, click **"Database Access"**
2. Click **"Add New Database User"**
3. Choose **"Password"** authentication
4. Enter credentials:
   - **Username:** `capstone_admin` (or your choice)
   - **Password:** Click **"Autogenerate Secure Password"** and **COPY IT**
5. Under **"Database User Privileges"**, select:
   - **"Read and write to any database"**
6. Click **"Add User"**

> ⚠️ **IMPORTANT:** Save your password! You won't see it again.

---

## Step 4: Whitelist Your IP Address

1. In the left sidebar, click **"Network Access"**
2. Click **"Add IP Address"**
3. Choose one of these options:

   **Option A - For Development (Recommended):**
   - Click **"Allow Access from Anywhere"**
   - This adds `0.0.0.0/0` (allows all IPs)
   
   **Option B - For Production:**
   - Click **"Add Current IP Address"**
   - Your current IP will be added

4. Click **"Confirm"**

> ⏳ Wait 1-2 minutes for changes to take effect

---

## Step 5: Get Your Connection String

1. In the left sidebar, click **"Database"**
2. Find your cluster and click **"Connect"**
3. Choose **"Connect your application"**
4. Select:
   - **Driver:** Python
   - **Version:** 3.12 or later
5. Copy the connection string. It looks like:

```
mongodb+srv://<username>:<password>@capstonecluster.xxxxx.mongodb.net/?retryWrites=true&w=majority
```

---

## Step 6: Update Your .env File

Open your `.env` file and update the MongoDB settings:

```env
# MongoDB Atlas Configuration
MONGODB_URI=mongodb+srv://capstone_admin:YOUR_PASSWORD_HERE@capstonecluster.xxxxx.mongodb.net/?retryWrites=true&w=majority&appName=CapstoneCluster
MONGODB_NAME=capstone_db
```

**Replace:**
- `capstone_admin` → Your database username
- `YOUR_PASSWORD_HERE` → Your database password (URL-encoded if special chars)
- `capstonecluster.xxxxx.mongodb.net` → Your actual cluster hostname

---

## Step 7: URL Encode Special Characters

If your password has special characters, encode them:

| Character | Encoded |
|-----------|---------|
| `@` | `%40` |
| `:` | `%3A` |
| `/` | `%2F` |
| `#` | `%23` |
| `?` | `%3F` |
| `&` | `%26` |
| `=` | `%3D` |
| `+` | `%2B` |
| `%` | `%25` |

**Example:**
- Password: `MyP@ss#123`
- Encoded: `MyP%40ss%23123`

---

## Step 8: Test the Connection

Run the Django server:

```bash
python manage.py runserver
```

If successful, you should see:
```
Starting development server at http://127.0.0.1:8000/
```

---

## Troubleshooting

### Error: SSL Handshake Failed
**Cause:** IP not whitelisted or network issues

**Fix:**
1. Go to **Network Access** in Atlas
2. Ensure your IP is whitelisted or add `0.0.0.0/0`
3. Wait 1-2 minutes for changes to propagate
4. Try connecting again

### Error: Authentication Failed
**Cause:** Wrong username/password

**Fix:**
1. Double-check your username and password
2. Make sure special characters are URL-encoded
3. Create a new database user if unsure

### Error: Connection Timeout
**Cause:** Firewall blocking connection

**Fix:**
1. Try a different network (e.g., mobile hotspot)
2. Check if your firewall allows outbound connections on port 27017
3. Try adding `&ssl=true&tlsAllowInvalidCertificates=true` to connection string (dev only)

---

## Sample .env Configuration

```env
# Django
DEBUG=True
SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=localhost,127.0.0.1

# MongoDB Atlas
MONGODB_URI=mongodb+srv://capstone_admin:MySecurePassword123@capstonecluster.abc123.mongodb.net/?retryWrites=true&w=majority&appName=CapstoneCluster
MONGODB_NAME=capstone_db

# Email (Gmail example)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password

# Redis (for Celery)
REDIS_URL=redis://localhost:6379/0
```

---

## Verify MongoDB Connection in Python

You can test your connection directly:

```python
from pymongo import MongoClient

uri = "mongodb+srv://capstone_admin:password@capstonecluster.abc123.mongodb.net/?retryWrites=true&w=majority"

try:
    client = MongoClient(uri)
    client.admin.command('ping')
    print("✅ Connected successfully to MongoDB Atlas!")
except Exception as e:
    print(f"❌ Connection failed: {e}")
```

Run with: `python -c "..."`

---

## Next Steps

Once connected:
1. Test the signup endpoint: `POST /api/auth/signup/`
2. Check MongoDB Atlas → **Browse Collections** to see your data
3. Continue with API testing using the [API Testing Guide](./API_TESTING_GUIDE.md)
