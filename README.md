# AzureAI Solution for Document Analysis
In this project, I worked on AI solution to extracting KPIs related to HR (It can change for other fields as well) from documents using Azure Document Intelligence and OpenAI and Lang chain and push them into the Azure SQL Server DB. 

The goal of this project is to provide a reference for companies that they can always compare their KPIs with Global standard values and understand how far they are. 

# Is it fit for who?
This project is a high level project that needs to have deep knowledge about Python, LLms, Lang Chain and Azure AI services that you can understand it and work with it. If you are interested, please make a PR on this project. I'm open to communication and meetings if needed.

# How to use this project

<span>1- Download or clone the repo. </span>
<span>2- Make a sql server DB in Azure.
<span>3- Run the query in Create Azure Sql DB.sql in your Azure SQL DB. It will create desire tables and feed one of the tables.</span>
<span>4- Run the app step by step: </span>
   <span>a) python3 -m venv myenv</span>
   <span>b) myenv\Scripts\activate </span>
   <span>c) pip install -r requirements.txt</span>
   <span>d) Python app.py</span>



