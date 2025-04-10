import os
import aiohttp
import aiofiles
import mimetypes
import json
from dotenv import load_dotenv
from openai import AzureOpenAI
from azure.storage.blob import BlobServiceClient
from quart import Quart, render_template, request, redirect, url_for
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient

#db
import urllib
from sqlalchemy import text
from dotenv import load_dotenv
import sqlalchemy as db
from sqlalchemy.orm import Session
from sqlalchemy.orm import declarative_base

# Kor!
from kor.extraction import create_extraction_chain
from kor.nodes import Object, Text, Number
from kor.encoders import JSONEncoder

# LangChain Models
from langchain.chat_models import ChatOpenAI
from langchain.llms import OpenAI
from langchain.chat_models import AzureChatOpenAI
from langchain_community.chat_models import AzureChatOpenAI
from langchain_community.llms import OpenAI


load_dotenv()

# Configure folder for uploaded files
app = Quart(__name__)
app.config['UPLOAD_FOLDER'] = 'data/'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Azure Blob Storage Configuration
azure_storage_connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
container_name = os.getenv("CONTAINER_NAME")

# Azure Document Intelligence
key = os.getenv("DOCUMENTINTELLIGENCE_API_KEY")
endpoint = os.getenv("DOCUMENTINTELLIGENCE_ENDPOINT")

# Azure OpenAI Configuration
openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
openai_api_key = os.getenv("AZURE_OPENAI_API_KEY")
deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")

#db configuration
driver_name = os.getenv("DRIVER_NAME")
server_name = os.getenv("SERVER_NAME")
database_name = os.getenv("DATABASE_NAME")
username = os.getenv("USERNAME_1")
password = os.getenv("PASSWORD")

# Create connection string
connection_string = (
    f'Driver={driver_name};'
    f'Server=tcp:{server_name}.database.windows.net,1433;'
    f'Database={database_name};'
    f'Uid={username};'
    f'Pwd={password};'
    'Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;'
)

# Initialize Blob Service Client
#blob_service_client = BlobServiceClient.from_connection_string(azure_storage_connection_string)
#container_client = blob_service_client.get_container_client(container_name)

def get_engine():
    params = urllib.parse.quote(connection_string)
    url = f"mssql+pyodbc:///?odbc_connect={params}"
    return db.create_engine(url)

def insert_to_db(data, selected_categories):
    """
    Insert extracted KPI data into database for each selected category
    
    Args:
        data (dict): Extracted KPI data
        selected_categories (list): List of categories selected by user
    """
    try:
        engine = get_engine()
        
        def convert_to_float_or_none(value):
            """Convert string values to float or None if invalid"""
            if value in ['N/A', '', None]:
                return None
            try:
                return float(value)
            except (ValueError, TypeError):
                return None

        # Map category names to their database IDs
        category_mapping = {
            'Demographic': 1,
            'Performance Data': 2,
            'Leave Policies': 3,
            'Salary Information': 4
        }

        with Session(engine) as session:
            try:
                # Process each selected category
                for selected_cat in selected_categories:
                    if selected_cat in category_mapping:
                        maincat_id = category_mapping[selected_cat]
                        
                        # Insert category information
                        print(f"Inserting category: {data['category_name']} with maincat_id: {maincat_id}")
                        session.execute(
                            text("""
                                INSERT INTO kpis_category (cat_name, cat_description, maincat_id) 
                                VALUES (:cat_name, :cat_description, :maincat_id)
                            """),
                            {
                                "cat_name": data["category_name"],
                                "cat_description": data["category_description"],
                                "maincat_id": maincat_id
                            }
                        )
                        session.flush()
                        
                        # Get the newly created category ID
                        result = session.execute(text("SELECT @@IDENTITY AS cat_id"))
                        category_id = result.scalar()
                        
                        # Insert KPIs for this category
                        for kpi in data["kpis"]:
                            # Insert KPI information
                            session.execute(
                                text("""
                                    INSERT INTO kpis (category_id, kpi_name, unit, kpi_source, kpi_description) 
                                    VALUES (:category_id, :kpi_name, :unit, :kpi_source, :kpi_description)
                                """),
                                {
                                    "category_id": category_id,
                                    "kpi_name": kpi["kpi_name"],
                                    "unit": kpi["unit"],
                                    "kpi_source": kpi["kpi_source"],
                                    "kpi_description": kpi["kpi_description"]
                                }
                            )
                            session.flush()
                            
                            # Get the newly created KPI ID
                            result = session.execute(text("SELECT @@IDENTITY AS kpi_id"))
                            kpi_id = result.scalar()
                            
                            # Insert standard values for this KPI
                            if "standard_values" in kpi:
                                for std_value in kpi["standard_values"]:
                                    session.execute(
                                        text("""
                                            INSERT INTO standard_values 
                                            (kpi_id, geographical_loc, country, industry, gender, 
                                             age_group, experience_level, value_avg, value_min, 
                                             value_max, source_val) 
                                            VALUES 
                                            (:kpi_id, :geographical_loc, :country, :industry, :gender,
                                             :age_group, :experience_level, :value_avg, :value_min,
                                             :value_max, :source_val)
                                        """),
                                        {
                                            "kpi_id": kpi_id,
                                            "geographical_loc": std_value["geographical_loc"],
                                            "country": std_value["country"],
                                            "industry": std_value["industry"],
                                            "gender": std_value["gender"],
                                            "age_group": std_value["age_group"],
                                            "experience_level": std_value["experience_level"],
                                            "value_avg": convert_to_float_or_none(std_value["value_avg"]),
                                            "value_min": convert_to_float_or_none(std_value["value_min"]),
                                            "value_max": convert_to_float_or_none(std_value["value_max"]),
                                            "source_val": std_value["source_val"]
                                        }
                                    )
                
                session.commit()
                return "Success"
                
            except Exception as e:
                session.rollback()
                raise e
                
    except Exception as e:
        print(f"Error in inserting to db: {str(e)}")
        return f"Error in inserting to db: {str(e)}"


async def open_ai(extracted_text, selected_categories):
    """
    Process extracted text using OpenAI to identify and structure KPI data
    
    Args:
        extracted_text (str): Text extracted from document
        selected_categories (list): Categories selected by user
    Returns:
        bool: True if processing successful, False otherwise
    """
    try:
        # Initialize Azure OpenAI
        llm = AzureChatOpenAI(
            openai_api_key=openai_api_key,
            azure_endpoint=openai_endpoint,
            model_name="gpt-4", 
            api_version="2024-08-01-preview"
        )

        # Define schema for standard values
        standard_values_schema = Object(
            id="standard_values",
            description="Standard values for a KPI",
            attributes=[
                Text(id="geographical_loc", description="The geographical location where the KPI data is applicable"),
                Text(id="country", description="The specific country for the KPI data"),
                Text(id="industry", description="The industry sector for the KPI data"),
                Text(id="gender", description="The gender demographic for the KPI data"),
                Text(id="age_group", description="The age group for the KPI data"),
                Text(id="experience_level", description="The experience level for the KPI data"),
                Text(id="value_avg", description="The average value of the KPI"),
                Text(id="value_min", description="The minimum value of the KPI"),
                Text(id="value_max", description="The maximum value of the KPI"),
                Text(id="source_val", description="The source of the KPI data values")
            ]
        )

        # Define schema for KPIs
        kpis_schema = Object(
            id="kpis",
            description="Individual KPI information",
            attributes=[
                Text(id="kpi_name", description="The name of the KPI"),
                Text(id="unit", description="The unit of measurement for the KPI"),
                Text(id="kpi_source", description="The source URL or reference for the KPI definition"),
                Text(id="kpi_description", description="A detailed description of what the KPI measures"),
                standard_values_schema
            ]
        )

        # Define main schema for KPI categories
        main_schema = Object(
            id="KPI_Category",
            description="KPIs related to Human Resources (HR) analysis",
            attributes=[
                Text(id="category_name", description="The name of the KPI category"),
                Text(id="category_description", description="A short description of the KPI category"),
                kpis_schema
            ],
            examples=[
                (
                    """December 2023
                WGEA Mining Industry Snapshot
                About this Snapshot
                . This Industry Snapshot is a summary of performance against the Gender Equality Indicators of all
                employers in the Mining industry from their 2022-23 submission to the Workplace Gender Equality
                Agency's (WGEA) annual Gender Equality Reporting.
                · Employers should read this Snapshot in conjunction with their 2022-23 WGEA Executive Summary,
                which details their organisation's performance against each Gender Equality Indicator, so that they
                can compare their performance against that of their industry.
                . Further comparisons of performance by industry or with other organisations, such as specific
                industry peers, is possible using WGEA's Data Explorer on the WGEA website. WGEA's annual
                Gender Equality Scorecard also provides industry-specific insights.
                Gender Pay Gap (GPG)
                The gender pay gap is the difference in average earnings between women and men in the workforce. It is
                not to be confused with women and men being paid the same for the same, or comparable, job - this is
                equal pay.
                The gender pay gap is a useful proxy for measuring and tracking gender equality across a nation, industry or
                within an organisation. Closing the gender pay gap is important for Australia's economic future and reflects
                our aspiration to be an equal and fair society for all.
                A positive percentage indicates that men are paid more on average than women. A negative percentage
                indicates that women are paid more on average than men.
                2020-21
                2021-22
                2022-23
                Average (mean) total remuneration
                14.1%
                14.2%
                12.7%
                Median total remuneration
                15.6%
                16.6%
                15.1%
                Average (mean) base salary
                11.2%
                11.9%
                9.9%
                Median base salary
                13.3%
                14.7%
                12.3%
                Note:
                · Part-time/casuals/part-year employee remuneration is annualised to full-time equivalent.
                · The 2022-23 gender pay gap calculation does not include voluntary salary data submitted for CEO, Head of Business(es),
                and Casual managers. It also excludes employees who did not receive any payment during the reporting period.
                · Employees identified as non-binary are excluded while the Agency establishes the baseline level for this new information.
                Workplace Gender Equality Agency | WGEA Mining Industry Snapshot | www.wgea.gov.au
                1
                Gender composition by pay quartile
                The chart below divides the Mining workforce into four equal quartiles of employees by total remuneration
                full-time equivalent pay. The number in each pay quartile represents the proportion of each gender.
                A disproportionate concentration of men in the upper quartiles and/or women in the lower quartiles can drive
                a positive gender pay gap.
                Average Total Remuneration
                Total Workforce
                22.0
                78.0
                $183,902
                Upper Quartile
                15.8
                84.2
                $288,066
                Upper Middle Quartile
                15.3
                84.7
                $186,896
                Lower Middle Quartile
                21.7
                78.3
                $153,332
                Lower Quartile
                35.3
                64.7
                $107,318
                0%
                20%
                40%
                60%
                80%
                Women
                Men
                Note: Part-time/casuals/part-year employee remuneration is annualised to full-time equivalent.
                Gender pay gap and composition by occupational
                group
                The chart below shows the average total remuneration gender pay gap and composition for manager
                category and non-manager occupations in the Mining industry for 2022-23.
                The aspiration is to remove the gender pay gap in favour of men or women, so a gender pay gap closer to
                zero is considered better.
                Managers
                Women
                Men
                Average total
                remuneration GPG
                All Managers
                23%
                77%
                3.7%
                Key Management Personnel
                23%
                77%
                0.4%
                Other Executives/General Managers
                23%
                77%
                0.2%
                Senior Managers
                25%
                75%
                4.3%
                Other Managers
                23%
                78%
                6.1%
                Non-managers
                Women
                Men
                Average total
                remuneration GPG
                All non-Managers
                22%
                78%
                15.2%
                Clerical and Administrative Workers
                72%
                28%
                22.0%
                Community and Personal Service
                Workers
                34%
                66%
                7.8%
                Sales Workers
                23%
                77%
                N/A
                Professionals
                31%
                69%
                14.0%
                Labourers
                17%
                83%
                16.7%
                Technicians and Trade Workers
                10%
                90%
                20.9%
                Machinery Operators and Drivers
                18%
                82%
                12.5%
                Note:
                · Percentages shown may not add up to 100% due to rounding of decimal place.
                · Gender pay gaps are not listed for manager/occupation categories when there are less than 100 women and men employees
                in a category, or there are less than five submission groups in that employee manager/occupation category.
                Workplace Gender Equality Agency | WGEA Mining Industry Snapshot | www.wgea.gov.au""",
                    {
                    "category_name": "Gender Pay Gap",
                    "category_description": "Difference in average earnings between women and men in the workforce",
                    "kpis": [
                    {
                        "kpi_name": "Average (mean) total remuneration",
                        "unit": "percentage",
                        "kpi_source": "WGEA Mining Industry Snapshot 2022-23",
                        "kpi_description": "The average total remuneration gender pay gap in the mining industry.",
                        "standard_values": [
                        {
                            "geographical_loc": "Australia",
                            "country": "Australia",
                            "industry": "Mining",
                            "gender": "Women vs Men",
                            "age_group": "All ages",
                            "experience_level": "All experience levels",
                            "value_avg": "12.7",
                            "value_min": "12.7",
                            "value_max": "14.2",
                            "source_val": "WGEA Mining Industry Snapshot"
                        }
                        ]
                    },
                    {
                        "kpi_name": "Median total remuneration",
                        "unit": "percentage",
                        "kpi_source": "WGEA Mining Industry Snapshot 2022-23",
                        "kpi_description": "The median total remuneration gender pay gap in the mining industry.",
                        "standard_values": [
                        {
                            "geographical_loc": "Australia",
                            "country": "Australia",
                            "industry": "Mining",
                            "gender": "Women vs Men",
                            "age_group": "All ages",
                            "experience_level": "All experience levels",
                            "value_avg": "15.1",
                            "value_min": "15.1",
                            "value_max": "16.6",
                            "source_val": "WGEA Mining Industry Snapshot"
                        }
                        ]
                    },
                    {
                        "kpi_name": "Average (mean) base salary",
                        "unit": "percentage",
                        "kpi_source": "WGEA Mining Industry Snapshot 2022-23",
                        "kpi_description": "The average base salary gender pay gap in the mining industry.",
                        "standard_values": [
                        {
                            "geographical_loc": "Australia",
                            "country": "Australia",
                            "industry": "Mining",
                            "gender": "Women vs Men",
                            "age_group": "All ages",
                            "experience_level": "All experience levels",
                            "value_avg": "9.9",
                            "value_min": "9.9",
                            "value_max": "11.9",
                            "source_val": "WGEA Mining Industry Snapshot"
                        }
                        ]
                    },
                    {
                        "kpi_name": "Median base salary",
                        "unit": "percentage",
                        "kpi_source": "WGEA Mining Industry Snapshot 2022-23",
                        "kpi_description": "The median base salary gender pay gap in the mining industry.",
                        "standard_values": [
                        {
                            "geographical_loc": "Australia",
                            "country": "Australia",
                            "industry": "Mining",
                            "gender": "Women vs Men",
                            "age_group": "All ages",
                            "experience_level": "All experience levels",
                            "value_avg": "12.3",
                            "value_min": "12.3",
                            "value_max": "14.7",
                            "source_val": "WGEA Mining Industry Snapshot"
                        }
                        ]
                    },
                    {
                        "kpi_name": "Average total remuneration by manager level",
                        "unit": "percentage",
                        "kpi_source": "WGEA Mining Industry Snapshot 2022-23",
                        "kpi_description": "The average total remuneration gender pay gap for managers in the mining industry.",
                        "standard_values": [
                        {
                            "geographical_loc": "Australia",
                            "country": "Australia",
                            "industry": "Mining",
                            "gender": "Women vs Men",
                            "age_group": "All ages",
                            "experience_level": "Managers",
                            "value_avg": "3.7",
                            "value_min": "0.2",
                            "value_max": "6.1",
                            "source_val": "WGEA Mining Industry Snapshot"
                        }
                        ]
                    },
                    {
                        "kpi_name": "Average total remuneration by non-manager level",
                        "unit": "percentage",
                        "kpi_source": "WGEA Mining Industry Snapshot 2022-23",
                        "kpi_description": "The average total remuneration gender pay gap for non-managers in the mining industry.",
                        "standard_values": [
                        {
                            "geographical_loc": "Australia",
                            "country": "Australia",
                            "industry": "Mining",
                            "gender": "Women vs Men",
                            "age_group": "All ages",
                            "experience_level": "Non-managers",
                            "value_avg": "15.2",
                            "value_min": "7.8",
                            "value_max": "22.0",
                            "source_val": "WGEA Mining Industry Snapshot"
                        }
                        ]
                    }
                    ]
                }
                )
            ]
        )

        # Create and execute extraction chain
        chain = create_extraction_chain(llm, main_schema, encoder_or_encoder_class=JSONEncoder)  
        output = chain.invoke(extracted_text)
        
        print("Raw extraction output:", json.dumps(output, indent=2))
        
        # Process extracted data
        if output and isinstance(output, dict) and "data" in output:
            data = output["data"]
            
            if isinstance(data, str):
                print(f"Skipping string data: {data}")
                return None
                
            # Process nested KPI_Category structure
            if isinstance(data, dict):
                if "KPI_Category" in data:
                    data = data["KPI_Category"]
                data_to_process = [data]
            elif isinstance(data, list):
                data_to_process = []
                for item in data:
                    if isinstance(item, dict) and "KPI_Category" in item:
                        data_to_process.append(item["KPI_Category"])
                    else:
                        data_to_process.append(item)
            else:
                print(f"Unexpected data type: {type(data)}")
                return None

            # Process each item in the extracted data
            for item in data_to_process:
                try:
                    if not isinstance(item, dict):
                        print(f"Skipping non-dictionary item: {item}")
                        continue
                        
                    required_fields = ["category_name", "category_description", "kpis"]
                    if not all(field in item for field in required_fields):
                        print(f"Missing required fields in item: {item}")
                        continue
                        
                    if not isinstance(item["kpis"], list):
                        print(f"Invalid kpis structure in item: {item}")
                        continue

                    insert_result = insert_to_db(item, selected_categories)
                    print(f"Database insertion result: {insert_result}")
                    
                except Exception as insert_error:
                    print(f"Error inserting item into database: {str(insert_error)}")
                    print(f"Item that caused error: {json.dumps(item, indent=2)}")
                    continue
            
            return True
            
        else:
            print("Invalid output structure")
            print(f"Output: {json.dumps(output, indent=2)}")
            return None
            
    except Exception as e:
        print(f"Error in open_ai function: {str(e)}")
        print(f"Full error details: {str(e.__class__.__name__)}: {str(e)}")
        return None

async def document_intelligence(file_path):
    """
    Extract text from uploaded document using Azure Document Intelligence
    
    Args:
        file_path (str): Path to the uploaded file
    Returns:
        str: Extracted text from the document
    """
    try:
        credential = AzureKeyCredential(key)
        client = DocumentIntelligenceClient(endpoint=endpoint, credential=credential)
        
        # Verify file type
        content_type, _ = mimetypes.guess_type(file_path)
        if not content_type:
            raise ValueError("Unsupported file type")

        # Read file and process with Document Intelligence
        async with aiofiles.open(file_path, "rb") as file:
            file_data = await file.read()
            
        poller = client.begin_analyze_document("prebuilt-layout", body=file_data)
        result = poller.result()
        
        # Extract text from all pages
        extracted_text = "\n".join([line.content for page in result.pages for line in page.lines])
        return extracted_text
    except Exception as e:
        print(f"Error in document_intelligence: {str(e)}")
        raise


# upload file blob storage, used async as we need ability to serve several request simultanusly
# async def upload_to_blob_storage(file_path, file_name):
#     """Uploads a file to Azure Blob Storage asynchronously."""
#     try:
#         blob_client = container_client.get_blob_client(file_name)
#         with open(file_path, "rb") as data:
#             blob_client.upload_blob(data, overwrite=True)
#         return f"File {file_name} uploaded to Azure Blob Storage successfully!"
#     except Exception as e:
#         return f"Error uploading to Azure Blob Storage: {str(e)}"

selected_categories=[]
@app.route('/', methods=['GET', 'POST'])
async def upload_file():
    """
    Handle file upload and processing
    GET: Display upload form
    POST: Process uploaded file and extract KPIs
    """
    if request.method == 'POST':
        try:
            # Get form data and file
            form = await request.form
            files = await request.files
            file = files.get('file')
            selected_categories = form.getlist('categories')

            # Validate inputs
            if not file:
                return await render_template('upload.html', error="No file uploaded")

            if not selected_categories:
                return await render_template('upload.html', error="Please select at least one category")

            # Save and process file
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            await file.save(file_path)

            # Extract text and process with OpenAI
            extracted_text = await document_intelligence(file_path)
            print(extracted_text)
            result = await open_ai(extracted_text, selected_categories)
            
            if result:
                return redirect(url_for('show_data'))
            else:
                return await render_template('upload.html', error="No data was extracted from the file")
                
        except Exception as e:
            print(f"Error processing file: {str(e)}")
            return await render_template('upload.html', error=f"Error: {str(e)}")

    # Display upload form with available categories
    categories = ['Demographic', 'Performance Data', 'Leave Policies', 'Salary Information']
    return await render_template('upload.html', categories=categories)

def fetch_all_data():
    """
    Fetch all KPI data from the database
    
    Returns:
        dict: Dictionary containing data from all tables
    """
    try:
        engine = get_engine()
        with Session(engine) as session:
            # Fetch data from all tables
            main_categories = session.execute(
                text("SELECT * FROM main_category")
            ).all()
            
            kpi_categories = session.execute(
                text("""
                    SELECT 
                        cat_id,
                        cat_name,
                        cat_description,
                        maincat_id
                    FROM kpis_category
                """)
            ).all()
            
            kpis = session.execute(
                text("""
                    SELECT 
                        kpi_id,
                        category_id,
                        kpi_name,
                        unit,
                        kpi_source,
                        kpi_description
                    FROM kpis
                """)
            ).all()
            
            standard_values = session.execute(
                text("""
                    SELECT 
                        kpi_id,
                        geographical_loc,
                        country,
                        industry,
                        gender,
                        age_group,
                        experience_level,
                        value_avg,
                        value_min,
                        value_max,
                        source_val
                    FROM standard_values
                """)
            ).all()
            
            # Convert results to dictionaries
            return {
                'main_categories': [
                    {column: value for column, value in row._mapping.items()}
                    for row in main_categories
                ],
                'kpi_categories': [
                    {column: value for column, value in row._mapping.items()}
                    for row in kpi_categories
                ],
                'kpis': [
                    {column: value for column, value in row._mapping.items()}
                    for row in kpis
                ],
                'standard_values': [
                    {column: value for column, value in row._mapping.items()}
                    for row in standard_values
                ]
            }
            
    except Exception as e:
        print(f"Error fetching data: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return None

@app.route('/show_data')
async def show_data():
    """
    Route handler for displaying all KPI data
    """
    try:
        all_data = fetch_all_data()
        if all_data:
            return await render_template('show_data.html', data=all_data)
        else:
            return await render_template('show_data.html', error="No data available")
    except Exception as e:
        return await render_template('show_data.html', error=f"Error: {str(e)}")

if __name__ == '__main__':
    app.run(debug=True)

