from django.urls import path
from documents.views import (
    DocumentUploadView,
    DocumentListView,
    DocumentDetailView,
    DocumentPreviewView,
    DocumentDownloadView,
    DocumentVerifyView,
    DocumentTypesView,
    RequestReuploadView
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

    # Preview document (auth + decryption)
    path('<str:document_id>/preview/', DocumentPreviewView.as_view(), name='document-preview'),

    # Legacy download path (alias to preview handler)
    path('<str:document_id>/download/', DocumentDownloadView.as_view(), name='document-download'),
    
    # Verify document (loan officer)
    path('<str:document_id>/verify/', DocumentVerifyView.as_view(), name='document-verify'),
    
    # Request re-upload (loan officer)
    path('<str:document_id>/request-reupload/', RequestReuploadView.as_view(), name='document-request-reupload'),
]
