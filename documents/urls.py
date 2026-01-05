from django.urls import path
from documents.views import (
    DocumentUploadView,
    DocumentListView,
    DocumentDetailView,
    DocumentVerifyView,
    DocumentTypesView
)

app_name = 'documents'

urlpatterns = [
    # Upload document
    path('upload/', DocumentUploadView.as_view(), name='document-upload'),
    
    # List all documents
    path('', DocumentListView.as_view(), name='document-list'),
    
    # Get document types
    path('types/', DocumentTypesView.as_view(), name='document-types'),
    
    # Document detail and delete
    path('<str:document_id>/', DocumentDetailView.as_view(), name='document-detail'),
    
    # Verify document (loan officer)
    path('<str:document_id>/verify/', DocumentVerifyView.as_view(), name='document-verify'),
]
