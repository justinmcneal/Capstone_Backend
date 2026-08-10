from django.urls import path

from documents.views import (
    DocumentDetailView,
    DocumentListView,
    DocumentPresignedFinalizeView,
    DocumentPresignedUploadView,
    DocumentTypesView,
    DocumentUploadView,
    DocumentVerifyView,
    RequestReuploadView,
)

app_name = "documents"

urlpatterns = [
    # Upload document
    path("upload/", DocumentUploadView.as_view(), name="document-upload"),
    # Direct client upload via presigned POST data
    path("presigned-upload/", DocumentPresignedUploadView.as_view(), name="document-presigned-upload"),
    path(
        "presigned-upload/<str:session_id>/finalize/",
        DocumentPresignedFinalizeView.as_view(),
        name="document-presigned-finalize",
    ),
    # List all documents
    path("", DocumentListView.as_view(), name="document-list"),
    # Get document types
    path("types/", DocumentTypesView.as_view(), name="document-types"),
    # Document detail and delete
    path("<str:document_id>/", DocumentDetailView.as_view(), name="document-detail"),
    # Verify document (loan officer)
    path( "<str:document_id>/verify/", DocumentVerifyView.as_view(), name="document-verify"),
    # Request re-upload (loan officer)
    path("<str:document_id>/request-reupload/", RequestReuploadView.as_view(), name="document-request-reupload"),
]
