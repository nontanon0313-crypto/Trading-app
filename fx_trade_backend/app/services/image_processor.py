"""
アップロードされた画像の検証・前処理
"""
from fastapi import UploadFile, HTTPException

ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
MAX_FILE_SIZE_MB = 10


async def validate_and_read_image(file: UploadFile) -> tuple[bytes, str]:
    """画像ファイルを検証し、バイト列とMIMEタイプを返す"""
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"対応していない画像形式です: {file.content_type}",
        )

    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=400,
            detail=f"画像サイズが大きすぎます({size_mb:.1f}MB > {MAX_FILE_SIZE_MB}MB)",
        )

    return content, file.content_type
