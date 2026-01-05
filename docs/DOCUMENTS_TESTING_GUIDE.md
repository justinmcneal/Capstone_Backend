# Document Upload API Testing Guide

Complete guide to test all document upload endpoints.

---

## Setup

**Base URL:** `http://localhost:8000/api/documents`

**Headers (all requests require authentication):**
```
Authorization: Bearer <customer_access_token>
Content-Type: application/json (for non-upload requests)
Content-Type: multipart/form-data (for uploads)
```

---

## Document Types

| Type | Description | Required |
|------|-------------|----------|
| `valid_id` | Government-issued ID | Yes (for loan) |
| `selfie_with_id` | Selfie holding ID | No |
| `proof_of_address` | Utility bill, barangay cert | No |
| `business_permit` | DTI/SEC/Mayor's permit | No |
| `business_photo` | Photo of business | No |
| `income_proof` | Bank statement (Optional for informal economy) | No |
| `other` | Other documents | No |

---

## Customer Endpoints

### 1. Get Document Types

```
GET /api/documents/types/
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "document_types": [
            {"value": "valid_id", "label": "Valid Government ID", "required": true},
            {"value": "selfie_with_id", "label": "Selfie with ID", "required": false},
            ...
        ]
    }
}
```

---

### 2. Upload Document

```
POST /api/documents/upload/
Content-Type: multipart/form-data
```

**Form Data:**
- `file` - The file (JPEG, PNG, PDF, max 10MB)
- `document_type` - One of the document types above
- `description` - Optional description

**Example using cURL:**
```bash
curl -X POST http://localhost:8000/api/documents/upload/ \
  -H "Authorization: Bearer <token>" \
  -F "file=@/path/to/document.jpg" \
  -F "document_type=valid_id" \
  -F "description=Driver's License"
```

**Response (201):**
```json
{
    "status": "success",
    "message": "Document uploaded successfully",
    "data": {
        "id": "678abc...",
        "document_type": "valid_id",
        "original_filename": "drivers_license.jpg",
        "file_size": 245678,
        "file_size_display": "239.9 KB",
        "status": "pending",
        "uploaded_at": "2025-01-05T14:30:00Z"
    }
}
```

---

### 3. List Documents

```
GET /api/documents/
```

**Query Params (optional):**
- `type=valid_id` - Filter by document type

**Response:**
```json
{
    "status": "success",
    "data": {
        "documents": [
            {
                "id": "678abc...",
                "document_type": "valid_id",
                "original_filename": "drivers_license.jpg",
                "file_size": 245678,
                "status": "pending",
                "verified": false,
                "file_url": "/media/documents/123/valid_id/20250105_abc123.jpg",
                "uploaded_at": "2025-01-05T14:30:00Z"
            }
        ],
        "total": 1
    }
}
```

---

### 4. Get Document Details

```
GET /api/documents/<document_id>/
```

---

### 5. Delete Document

```
DELETE /api/documents/<document_id>/
```

> ⚠️ Cannot delete verified documents

---

## Loan Officer Endpoints

### 6. Verify Document

```
PUT /api/documents/<document_id>/verify/
```

**Headers:** `Authorization: Bearer <loan_officer_access_token>`

**Request Body (Approve):**
```json
{
    "action": "approve",
    "notes": "Document verified successfully"
}
```

**Request Body (Reject):**
```json
{
    "action": "reject",
    "rejection_reason": "Document is blurry and unreadable",
    "notes": "Please upload a clearer image"
}
```

---

## Testing Flow

1. **Login as customer** → Get access token
2. **Get document types** → `GET /api/documents/types/`
3. **Upload document** → `POST /api/documents/upload/`
4. **List documents** → `GET /api/documents/`
5. **Login as loan officer** → Get token
6. **Verify document** → `PUT /api/documents/<id>/verify/`

---

## Error Responses

### File Too Large
```json
{
    "status": "error",
    "message": "File size exceeds maximum allowed (10MB)"
}
```

### Invalid File Type
```json
{
    "status": "error",
    "message": "Invalid file type. Allowed types: JPEG, PNG, PDF"
}
```

### Cannot Delete Verified
```json
{
    "status": "error",
    "message": "Cannot delete verified documents"
}
```
