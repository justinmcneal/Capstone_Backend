# Active Loans Search Fix - Multi-Word Name Support

## Bug Description
The active loans search endpoint failed when searching for customer names with spaces (e.g., "Gab Soriano").

### Issue Behavior
- ✅ `?search=gab` → Returns "Gab Soriano" (worked)
- ❌ `?search=Gab+Soriano` → Returns 0 results (failed)
- ❌ `?search=gab+soriano` → Returns 0 results (failed)

## Root Cause
The original search logic used a single regex pattern that searched for the entire query string within individual fields (`first_name`, `last_name`, `phone`, `email`). When searching for "Gab Soriano", it tried to find that exact phrase within a single field, which failed because:
- `first_name = "Gab"` doesn't contain "Gab Soriano"
- `last_name = "Soriano"` doesn't contain "Gab Soriano"

## Solution Implemented
Updated the search logic in `loans/views/officer_views.py` (ActiveLoansView) to handle multi-word queries:

1. **Split the search query by spaces** into individual words
2. **For multi-word queries**: Create MongoDB query conditions where ALL words must be found across `first_name` OR `last_name`
3. **For single-word queries**: Keep the original behavior for backwards compatibility

### MongoDB Query Logic
For search query "Gab Soriano", the new logic generates:
```python
{
    "$or": [
        {
            "$and": [
                {"$or": [{"first_name": /.*gab.*/i}, {"last_name": /.*gab.*/i}]},
                {"$or": [{"first_name": /.*soriano.*/i}, {"last_name": /.*soriano.*/i}]}
            ]
        },
        {"phone": /.*Gab Soriano.*/i},
        {"email": /.*Gab Soriano.*/i}
    ]
}
```

This matches customers where:
- ("Gab" is in first_name OR last_name) AND ("Soriano" is in first_name OR last_name)
- OR the full phrase matches phone/email fields

## Expected Behavior After Fix
- ✅ `?search=gab` → Returns "Gab Soriano" 
- ✅ `?search=soriano` → Returns "Gab Soriano"
- ✅ `?search=Gab+Soriano` → Returns "Gab Soriano" (now works!)
- ✅ `?search=gab+soriano` → Returns "Gab Soriano" (now works!)
- ✅ Case-insensitive matching preserved
- ✅ Phone and email search still work with full query
- ✅ Single-word searches maintain original behavior

## Testing Recommendations
1. Test with two-word names: "Gab Soriano", "John Doe"
2. Test with three-word names: "Mary Jane Smith"
3. Test with partial matches: "Gab Sor", "john do"
4. Test case variations: "GAB SORIANO", "gab soriano", "Gab soriano"
5. Test single-word searches: "Gab", "Soriano" (should still work)
6. Test phone/email searches (should still work)
7. Test with loan officer role filtering (assigned_officer check)

## Files Modified
- `loans/views/officer_views.py` - ActiveLoansView.get() method (lines ~1553-1597)
