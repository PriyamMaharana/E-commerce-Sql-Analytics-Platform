create database Ecommerce_Analytics;
go

use Ecommerce_Analytics;
go

-- stagging table
-- raw data lands here before transformation
create table stg_orders (
	order_id nvarchar(50),
	customer_id nvarchar(50),
	order_status nvarchar(20),
	order_purchase_timestamp nvarchar(30),
	order_approved_at nvarchar(30),
	order_delivered_date nvarchar(30),
	order_estimated_date nvarchar(30)
);
go

create table stg_order_items (
	order_id nvarchar(50),
	order_item_id int,
	product_id nvarchar(50),
	seller_id nvarchar(50),
	shipping_limit_date nvarchar(30),
	price decimal(10,2),
	freight_value decimal(10,2)
);
go

create table stg_customers (
	customer_id nvarchar(50),
	customer_unique_id nvarchar(50),
	customer_zip_code_prefix nvarchar(10),
	customer_city nvarchar(100),
	customer_state nvarchar(20)
);
go

create table stg_products (
	product_id nvarchar(50),
	category_name nvarchar(100),
	name_length int,
	description_length int,
	photos_qty int,
	weight_g decimal(10,2),
	length_cm decimal(10,2),
	height_cm decimal(10,2),
	width_cm decimal(10,2)
);
go

create table stg_sellers (
	seller_id nvarchar(50),
	zip_code nvarchar(10),
	city nvarchar(100),
	state nvarchar(20)
);
go

create table stg_payments (
	order_id nvarchar(50),
	payment_sequential int,
	payment_type nvarchar(20),
	payment_installments int,
	payment_value decimal(10,2)
);
go

CREATE TABLE stg_reviews (
    review_id VARCHAR(50),
    order_id VARCHAR(50),845
    review_score INT,
    review_comment_title NVARCHAR(100),
    review_comment_message NVARCHAR(MAX),
    review_creation_date DATETIME,
    review_answer_timestamp DATETIME
);
go

-- dimension tables
create table dim_customer (
	customer_sk int primary key identity(1,1),
	customer_id nvarchar(50) not null,
	customer_unique_id nvarchar(50),
	city nvarchar(100),
	state nvarchar(20),
	zip_code nvarchar(10)
);
go

create table dim_product (
	product_sk int primary key identity(1,1),
	product_id nvarchar(50) not null,
	category_name nvarchar(100),
	category_english nvarchar(100),
	photos_qty int, 
	weight_g decimal(10,2)
);
go

create table dim_seller (
	seller_sk int primary key identity(1,1),
	seller_id nvarchar(50) not null,
	city nvarchar(100),
	state nvarchar(20),
	zip_code nvarchar(10)
);
go

create table dim_date (
	date_sk int primary key,
	full_date date,
	day int,
	month int,
	month_name nvarchar(10),
	quarter int,
	year int,
	is_weekend bit,
	day_of_week nvarchar(10)
);
go

-- fact tables
create table fact_orders (
	order_sk int primary key identity(1,1),
	order_id nvarchar(50),
	customer_sk int references dim_customer(customer_sk),
	product_sk int references dim_product(product_sk),
	seller_sk int references dim_seller(seller_sk),
	date_sk int references dim_date(date_sk),
	order_item_id int,
	order_status nvarchar(20),
	price_brl decimal(10,2),
	freight_brl decimal(10,2),
	price_inr decimal(12,2),
	freight_inr decimal(12,2),
	payment_value decimal(10,2),
	payment_type nvarchar(20),
	review_score int, 
	delivery_days int,
	is_late_delivery bit
);
go

print 'E-Commerce_Analytics Schema Created.!!'


