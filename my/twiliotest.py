from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as XLImage
from PIL import Image as PILImage
import imagehash
import cv2
import pandas as pd
import re
import base64
import os
import json
from io import BytesIO

# Initialize FastAPI
app = FastAPI()

# Load configuration from config.json
with open('config.json', 'r') as config_file:
    config = json.load(config_file)

main_folder_path = config.get('main_folder_path', "")
comparison_images_folder_path = config['comparison_images_folder_path']
output_path = config['output_path']
images_output_path = config['images_output_path']
base_url = config['base_url']
image_similarity_threshold = config['image_similarity_threshold']

# Create output directories if they don't exist
for path in [output_path, images_output_path]:
    if not os.path.exists(path):
        os.makedirs(path)

# Function to calculate perceptual hash for an image
def get_image_hash(image_path):
    img = PILImage.open(image_path)
    return imagehash.phash(img)

# Helper function to check if an image is similar (within a threshold)
def is_similar_image(image_file, comparison_hashes, threshold=image_similarity_threshold):
    image_hash = get_image_hash(image_file)
    for comparison_hash in comparison_hashes:
        if abs(image_hash - comparison_hash) <= threshold:
            return True
    return False

# Function to detect barcodes using OpenCV
def contains_barcode(image_path):
    img = cv2.imread(image_path)
    gray_img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    barcode_detector = cv2.QRCodeDetector()
    data, _, _ = barcode_detector.detectAndDecode(gray_img)
    return bool(data)

# Load and hash all images from the comparison images folder
def load_comparison_image_hashes(folder_path):
    comparison_hashes = []
    for filename in os.listdir(folder_path):
        if filename.endswith((".png", ".jpg", ".jpeg")):
            image_path = os.path.join(folder_path, filename)
            comparison_hashes.append(get_image_hash(image_path))
    return comparison_hashes

# Regular expression pattern for report numbers
report_number_pattern = re.compile(r"(Report Number[s]*)\s+([A-Za-z0-9]+)")

# Function to extract report numbers into two columns
def extract_report_numbers(df):
    for idx, row in df.iterrows():
        for col_idx, cell_value in enumerate(row):
            if isinstance(cell_value, str):
                match = report_number_pattern.search(cell_value)
                if match:
                    df.at[idx, col_idx] = match.group(1)
                    df.at[idx, col_idx + 1] = match.group(2)
    return df

# Function to get report number from DataFrame
def get_report_number_from_df(df):
    for idx, row in df.iterrows():
        for col in df.columns:
            value = row[col]
            if isinstance(value, str):
                match = re.search(r"Report Number[s]*\s+([A-Za-z0-9]+)", value)
                if match:
                    return match.group(1).strip()
                elif value.strip().startswith('I') and re.match(r'^I\d+T$', value.strip()):
                    return value.strip()
    return None

# Helper function to convert image to base64
def convert_image_to_base64(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

# Helper function to create paths and URLs for images
def create_image_paths(image_filename, report_images_folder, base_url=base_url):
    abs_path = os.path.abspath(os.path.join(report_images_folder, image_filename))
    rel_path = os.path.relpath(abs_path, start=output_path)
    abs_url = f"{base_url}/{image_filename}"
    rel_url = f"/{rel_path.replace(os.sep, '/')}"
    
    return {"rel_path": rel_path, "rel_url": rel_url, "abs_path": abs_path, "abs_url": abs_url}

# Function to convert DataFrame to JSON format
def df_to_key_value_json(df, image_data, report_number):
    json_data = {
        "report_number": report_number,
        "date": "",
        "stones": [],
        "assets": image_data
    }
    current_item = {}
    misc_keys = []
    date_pattern = re.compile(r"\b\d{2}\.\d{2}\.\d{4}\b")

    for col in df.columns:
        for idx, value in enumerate(df[col]):
            if isinstance(value, str) and date_pattern.match(value):
                json_data["date"] = value

    for col in range(0, len(df.columns), 2):
        if col + 1 < len(df.columns):
            key_col = df.columns[col]
            value_col = df.columns[col + 1]
            for idx, row in df.iterrows():
                key_value = row[key_col] if pd.notnull(row[key_col]) else None
                value_value = row[value_col] if pd.notnull(row[value_col]) else None
                if pd.isnull(key_value) and pd.isnull(value_value):
                    if current_item:
                        json_data["stones"].append(current_item)
                        current_item = {}
                else:
                    if key_value:
                        key = str(key_value).strip().lower().replace(" ", "_")
                        if key != "report_number":
                            current_item[key] = value_value
    if current_item:
        json_data["stones"].append(current_item)

    if misc_keys:
        json_data["miscellaneous"] = misc_keys

    return json_data

@app.post("/process_excel/")
async def process_excel(file: UploadFile = File(...)):
    try:
        # Load uploaded file
        file_content = await file.read()
        comparison_hashes = load_comparison_image_hashes(comparison_images_folder_path)

        # Load workbook and process data
        wb = load_workbook(BytesIO(file_content), data_only=True)
        ws = wb.active
        data = list(ws.values)
        df = pd.DataFrame(data)

        for idx, row in df.iterrows():
            if pd.isnull(row[0]) and pd.notnull(row[1]):
                df.at[idx, 0] = df.at[idx, 1]
                df.at[idx, 1] = None

        df = df.dropna(axis=1, how='all')
        df = extract_report_numbers(df)

        report_number = get_report_number_from_df(df)
        base_filename = f"Report_Number_{report_number}" if report_number else f"output_{file.filename}"
        output_excel_path = os.path.join(output_path, f'{base_filename}.xlsx')

        df.to_excel(output_excel_path, index=False, header=False)

        image_data_paths = []
        for idx, image in enumerate(ws._images):
            img_filename = f"{report_number}_image_{idx+1}.png" if report_number else f"image_{idx+1}.png"
            img_path = os.path.join(images_output_path, img_filename)

            with open(img_path, 'wb') as img_file:
                img_file.write(image._data())

            if not contains_barcode(img_path) and not is_similar_image(img_path, comparison_hashes):
                path_info = create_image_paths(img_filename, images_output_path)
                image_data_paths.append(path_info)

        df_json_data = df_to_key_value_json(df, image_data_paths, report_number)
        json_output_path = os.path.join(output_path, f"{base_filename}.json")

        with open(json_output_path, 'w') as json_file:
            json.dump(df_json_data, json_file, indent=4)

        return JSONResponse(content=df_json_data)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
