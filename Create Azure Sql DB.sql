
CREATE TABLE kpis_category (
  cat_id INT IDENTITY(1,1) PRIMARY KEY,
  cat_name NVARCHAR(50), 
  cat_description NVARCHAR(200),
  maincat_id INT
)

CREATE TABLE kpis (
  kpi_id INT IDENTITY(1,1) PRIMARY KEY,
  category_id INT, 
  kpi_name NVARCHAR(200),
  unit NVARCHAR(50),
  kpi_source NVARCHAR(500),
  kpi_description NVARCHAR(500)
)

CREATE TABLE standard_values (
  standard_val_id INT IDENTITY(1,1) PRIMARY KEY,
  kpi_id INT,
  geographical_loc NVARCHAR(100), 
  country NVARCHAR(100),
  industry NVARCHAR(100),
  gender NVARCHAR(50),
  age_group NVARCHAR(50),
  experience_level NVARCHAR(50),
  value_avg REAL,
  value_min REAL,
  value_max REAL,
  source_val NVARCHAR(500)
)


CREATE TABLE main_category (
  maincat_id int IDENTITY(1,1) PRIMARY KEY,
  main_category_name NVARCHAR(50)
)

INSERT INTO main_category (main_category_name)
VALUES 
  ('Demographic'),
  ('Performance Data'),
  ('Leave Policies'),
  ('Salary Information');
