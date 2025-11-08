from pydantic import BaseModel, Field
from typing import List, Dict, Any

# Input/Output models for tools

class AddInput(BaseModel):
    a: int
    b: int

class AddOutput(BaseModel):
    result: int

class SqrtInput(BaseModel):
    a: int

class SqrtOutput(BaseModel):
    result: float

class StringsToIntsInput(BaseModel):
    string: str

class StringsToIntsOutput(BaseModel):
    ascii_values: List[int]

class ExpSumInput(BaseModel):
    int_list: List[int] = Field(alias="numbers")

class ExpSumOutput(BaseModel):
    result: float

class PythonCodeInput(BaseModel):
    code: str

class PythonCodeOutput(BaseModel):
    result: str

class UrlInput(BaseModel):
    url: str

class FilePathInput(BaseModel):
    file_path: str

class MarkdownInput(BaseModel):
    text: str

class MarkdownOutput(BaseModel):
    markdown: str

class ChunkListOutput(BaseModel):
    chunks: List[str]

class ShellCommandInput(BaseModel):
    command: str

# Models for mcp_sse_gmail.py
class GmailSendInput(BaseModel):
    to: str
    subject: str
    body: str

class GmailSendOutput(BaseModel):
    success: bool
    message_id: str = None
    error: str = None

class GmailSearchInput(BaseModel):
    query: str
    limit: int = 10

class GmailSearchOutput(BaseModel):
    emails: List[Dict[str, Any]]
    count: int
    error: str = None

# Models for mcp_sse_gdrive.py
class GDriveShareInput(BaseModel):
    file_id: str
    email: str = None
    role: str = "reader"

class GDriveShareOutput(BaseModel):
    success: bool
    share_url: str = None
    permission_id: str = None
    error: str = None

# Models for mcp_sse_sheets.py
class SheetsCreateInput(BaseModel):
    title: str
    folder_id: str = None

class SheetsCreateOutput(BaseModel):
    success: bool
    sheet_id: str = None
    sheet_url: str = None
    error: str = None

class SheetsUpdateInput(BaseModel):
    sheet_id: str
    range: str
    values: List[List[Any]]

class SheetsUpdateOutput(BaseModel):
    success: bool
    updated_cells: int = None
    error: str = None
