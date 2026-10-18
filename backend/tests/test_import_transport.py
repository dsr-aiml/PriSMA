import base64
import io
import json
import zipfile

import pytest
from test_baseline import register

from app import jobs
from app.source_intake import inspect_upload


@pytest.mark.parametrize("mime",["application/vnd.prisma.files+json","application/json, application/vnd.prisma.files+json"])
def test_folder_import_reaches_analysis_with_byte_encoded_sources(context,mime):
    client,_,_=context
    register(client)
    files={
        "app/package.json":json.dumps({"name":"app","dependencies":{"fastapi":"0.1"}}).encode("utf-16"),
        "app/api.py":'from fastapi import FastAPI\napp = FastAPI()\n@app.get("/items")\ndef items():\n    return []\n'.encode("utf-8"),
        "app/README.md":"The API service’s routes are declared in api.py.".encode("cp1252"),
    }
    response=client.post("/sources/preview?filename=app",headers={"content-type":mime},content=json.dumps({"files":[{"path":path,"data":base64.b64encode(raw).decode(),"size":len(raw)} for path,raw in files.items()]}))
    assert response.status_code==200,response.text
    review=response.json()
    assert review["retained"]==3 and review["excluded"]==0
    response=client.post("/investigations/bundle",json={"domain":"Folder app","bundle_id":review["bundle_id"],"selected":[row["id"] for row in review["sources"]],"provider":"rules"})
    assert response.status_code==202,response.text
    jobs.process(response.json()["id"])
    detail=client.get("/investigations/"+response.json()["id"]).json()
    assert detail["status"]=="completed" and detail["report"]["api_endpoints"][0]["path"]=="/items"
    assert any("service’s" in row["content"] for row in detail["evidence"])


@pytest.mark.parametrize("encoding",["utf-8","utf-16","utf-16-le","utf-16-be","utf-32","cp1252"])
def test_single_files_and_zip_members_share_decoding(encoding):
    text="The API service calls the Worker service to process customer requests.\n"
    if encoding=="cp1252":text+="The worker’s role is documented.\n"
    raw=text.encode(encoding)
    direct=inspect_upload("architecture.md",raw)
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,"w") as output:output.writestr("project/architecture.md",raw)
    zipped=inspect_upload("project.zip",archive.getvalue())
    assert direct["retained"]==zipped["retained"]==1
    assert direct["sources"][0]["source"]["content"]==zipped["sources"][0]["source"]["content"]==text


def test_unreadable_documents_name_the_file_and_do_not_echo_contents():
    private=b"private-input-contents\x00\x01\x02\x03"
    with pytest.raises(ValueError) as error:inspect_upload("app/notes.md",private)
    assert "app/notes.md: Binary content" in str(error.value)
    assert "private-input-contents" not in str(error.value)
    with pytest.raises(ValueError) as error:inspect_upload("scan.pdf",b"not a PDF")
    assert "scan.pdf:" in str(error.value) and "Unreadable or malformed document" not in str(error.value)


def test_folder_empty_paths_and_oversize_markers_are_specific():
    with pytest.raises(ValueError,match="Invalid folder file record"):
        inspect_upload("folder",b"",files=[{"path":"","content":"something"}])
    with pytest.raises(ValueError,match="large.py: Individual file exceeds 2 MB"):
        inspect_upload("folder",b"",files=[{"path":"large.py","content":"","size":2_000_001}])
