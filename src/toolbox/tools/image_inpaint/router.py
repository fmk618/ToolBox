"""Image inpainting — remove watermarks, text, logos by painting a mask."""

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
import numpy as np
import cv2

router = APIRouter(tags=["image-inpaint"])


@router.post("/remove")
async def remove_region(
    file: UploadFile = File(..., description="Original image"),
    mask: UploadFile = File(..., description="Black/white mask PNG — white = remove"),
):
    """Inpaint the masked region.

    Accepts any image format supported by OpenCV.
    The mask must be the same resolution as the image (frontend guarantees this).
    Returns a PNG of the repaired image.
    """
    img_bytes = await file.read()
    mask_bytes = await mask.read()

    img_arr = np.frombuffer(img_bytes, np.uint8)
    mask_arr = np.frombuffer(mask_bytes, np.uint8)

    img = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
    mask_img = cv2.imdecode(mask_arr, cv2.IMREAD_GRAYSCALE)

    if img is None:
        raise HTTPException(400, "无法解析图片文件")
    if mask_img is None:
        raise HTTPException(400, "无法解析遮罩文件")

    if mask_img.shape[:2] != img.shape[:2]:
        mask_img = cv2.resize(
            mask_img,
            (img.shape[1], img.shape[0]),
            interpolation=cv2.INTER_NEAREST,
        )

    _, binary_mask = cv2.threshold(mask_img, 128, 255, cv2.THRESH_BINARY)

    # Dilate for cleaner edges
    kernel = np.ones((3, 3), np.uint8)
    binary_mask = cv2.dilate(binary_mask, kernel, iterations=2)

    result = cv2.inpaint(img, binary_mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)

    _, buf = cv2.imencode(".png", result)
    return Response(content=buf.tobytes(), media_type="image/png")
