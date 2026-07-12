__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from rootact.handshake import raise_request, list_pending, answer


@pytest.fixture
def handshake_queue_path():
    """Create a temporary file for the handshake queue."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write("")
        temp_path = f.name
    yield Path(temp_path)
    os.unlink(temp_path)


@pytest.fixture
def mock_queue_path(handshake_queue_path):
    """Mock the environment variable to point to the temporary file."""
    with mock.patch.dict(os.environ, {"RACT_HANDSHAKE_QUEUE": str(handshake_queue_path)}):
        yield handshake_queue_path


def test_raise_request(mock_queue_path):
    """Test raising a request and verifying it's in the queue."""
    question = "What is the meaning of life?"
    context = {"user": "test_user"}
    
    request_id = raise_request(question, context)
    
    assert request_id is not None
    
    # Verify the entry exists in the file
    with open(mock_queue_path, "r") as f:
        lines = f.readlines()
    
    assert len(lines) == 1
    entry = json.loads(lines[0])
    
    assert entry["id"] == request_id
    assert entry["question"] == question
    assert entry["context"] == context
    assert entry["status"] == "pending"
    assert entry["answer"] is None
    assert entry["signer"] is None
    assert entry["answered_at"] is None


def test_list_pending(mock_queue_path):
    """Test listing pending requests."""
    # Raise two requests
    id1 = raise_request("Question 1", {"key": "val1"})
    id2 = raise_request("Question 2", {"key": "val2"})
    
    pending = list_pending()
    
    assert len(pending) == 2
    ids = {e["id"] for e in pending}
    assert ids == {id1, id2}


def test_answer_request(mock_queue_path):
    """Test answering a request and verifying the state change."""
    question = "What is 2+2?"
    context = {"math": True}
    request_id = raise_request(question, context)
    
    # Verify it's pending
    pending = list_pending()
    assert len(pending) == 1
    assert pending[0]["id"] == request_id
    
    # Answer the request
    response = "4"
    signer = "test_signer"
    result = answer(request_id, response, signer)
    
    assert result is True
    
    # Verify it's no longer pending
    pending = list_pending()
    assert len(pending) == 0
    
    # Verify the entry in the file is updated
    with open(mock_queue_path, "r") as f:
        lines = f.readlines()
    
    assert len(lines) == 1
    entry = json.loads(lines[0])
    
    assert entry["id"] == request_id
    assert entry["status"] == "answered"
    assert entry["answer"] == response
    assert entry["signer"] == signer
    assert entry["answered_at"] is not None


def test_answer_nonexistent_request(mock_queue_path):
    """Test answering a request that doesn't exist."""
    fake_id = "nonexistent-id"
    result = answer(fake_id, "response", "signer")
    assert result is False


def test_answer_already_answered_request(mock_queue_path):
    """Test answering a request that is already answered."""
    question = "Question"
    context = {}
    request_id = raise_request(question, context)
    
    # Answer it once
    answer(request_id, "Response 1", "Signer 1")
    
    # Try to answer it again
    result = answer(request_id, "Response 2", "Signer 2")
    assert result is False
    
    # Verify the first answer is still there
    with open(mock_queue_path, "r") as f:
        lines = f.readlines()
    
    entry = json.loads(lines[0])
    assert entry["answer"] == "Response 1"
    assert entry["signer"] == "Signer 1"


def test_list_pending_after_answer(mock_queue_path):
    """Test that answered requests are not returned by list_pending."""
    id1 = raise_request("Question 1", {})
    id2 = raise_request("Question 2", {})
    
    answer(id1, "Answer 1", "Signer 1")
    
    pending = list_pending()
    assert len(pending) == 1
    assert pending[0]["id"] == id2
