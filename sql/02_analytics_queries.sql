use Ecommerce_Analytics;
go

-- category 1: windows function
-- Q1: running total revenue by month
select
	d.year, d.month_name, 
	round(sum(f.price_inr), 2) as monthly_revenue,
	round(sum(sum(f.price_inr)) over (
		partition by d.year
		order by d.month
		rows unbounded preceding
	),2) as ytd_revenue
from fact_orders f
join dim_date d on f.date_sk = d.date_sk
where f.order_status = 'delivered'
group by d.year, d.month, d.month_name
order by d.year, d.month;


-- Q2: rank seller by revnue within each state
select
	ds.state, ds.seller_id,
	round(sum(f.price_inr),2) as total_revenue,
	rank() over(
		partition by ds.state
		order by sum(f.price_inr) desc
	) as state_rank
from fact_orders f
join dim_seller ds on f.seller_sk = ds.seller_sk
where f.order_status = 'delivered'
group by ds.state, ds.seller_id
order by ds.state, state_rank;


-- Q3: Month-over-month revenue growth %
with monthly as (
	select
		d.year, d.month, sum(f.price_inr) as revenue
	from fact_orders f
	join dim_date d on f.date_sk = d.date_sk
	where f.order_status = 'delivered'
	group by d.year, d.month
)
select 
	year, month, round(revenue, 2), 
	round(lag(revenue) over (
		order by year, month), 2) as previous_month,
	round((revenue - lag(revenue) over (
		order by year, month)) / nullif(lag(revenue) over (
		order by year, month),0)*100,2) as growth_pct
from monthly
order by year, month;


-- Q4: Top 3 product per category by revenue
with ranked as (
	select
		dp.category_name, dp.product_id,
		round(sum(f.price_inr),2) as revenue,
		dense_rank() over (
			partition by dp.category_name
			order by sum(f.price_inr) desc
		) as rnk
	from fact_orders f
	join dim_product dp on f.product_sk = dp.product_sk
	where f.order_status = 'delivered'
	group by dp.category_name, dp.product_id
)
select category_name, product_id, revenue, rnk
from ranked
where rnk <=3
order by category_name, rnk;


-- Q5: customer order frequency buckets using ntile
select
	order_bucket, 
	count(*) as customer_count,
	round(avg(total_orders),1) as avg_orders
from (
	select
		dc.customer_unique_id,
		count(distinct f.order_id) as total_orders,
		ntile(4) over (
			order by count(distinct f.order_id)
		) as order_bucket
	from fact_orders f
	join dim_customer dc on f.customer_sk = dc.customer_sk
	group by dc.customer_unique_id
) t
group by order_bucket
order by order_bucket;


-- category 2: CTEs (asked constantly)
-- Q6: late delivery rate by seller state
with delivery_stats as (
	select
		ds.state, count(*) as total_orders,
		sum(cast(f.is_late_delivery as int)) as late_orders
	from fact_orders f
	join dim_seller ds on f.seller_sk = ds.seller_sk
	where f.order_status = 'delivered'
		and f.delivery_days is not null
	group by ds.state
)
select
	state, total_orders, late_orders,
	round((late_orders *100.0 / total_orders), 2) as late_rate_pct
from delivery_stats
where total_orders >=50
order by late_rate_pct desc;


-- Q7: customer who spent more than avg
with customer_spend as (
	select
		dc.customer_unique_id, dc.state,
		round(sum(f.price_inr), 2) as total_spend
	from fact_orders f
	join dim_customer dc on f.customer_sk = dc.customer_sk
	where f.order_status = 'delivered'
	group by dc.customer_unique_id, dc.state
),
avg_spend as (
	select 
		round(avg(total_spend),3) as avg
	from customer_spend
)
select
	cs.customer_unique_id, cs.state, 
	cs.total_spend, av.avg as platform_avg,
	round((cs.total_spend - av.avg),2) as above_avg_by
from customer_spend cs
cross join avg_spend av
where cs.total_spend > av.avg
order by cs.total_spend desc;


-- Q8: product category revenue contribution %
with category_rev as (
	select
		dp.category_name, 
		sum(f.price_inr) as category_revenue
	from fact_orders f
	join dim_product dp on f.product_sk = dp.product_sk
	where f.order_status = 'delivered'
	group by dp.category_name
),
total as (
	select
		sum(category_revenue) as total_revenue
	from category_rev
)
select top 15
	cr.category_name, 
	round(cr.category_revenue, 2) as revenue,
	round((cr.category_revenue / t.total_revenue*100),2) as revenue_pct,
	sum(round((cr.category_revenue / t.total_revenue*100),2)) over (
		order by cr.category_revenue desc
		rows unbounded preceding
	) as cumulative_pct
from category_rev cr
cross join total t
order by cr.category_revenue desc;


-- category 3: stored procedure
-- Q9: SP1 - monthly revenue report for any year
create or alter procedure usp_MonthlyRevenue
	@year int = 2018
as 
begin
	set nocount on;

	select
		d.month, d.month_name,
		count(distinct f.order_id) as total_orders,
		count(distinct f.customer_sk) as unique_customers,
		round(sum(f.price_inr),2) as gross_revenue_inr,
		round(sum(f.freight_inr),2) as total_freight_inr,
		round(avg(f.price_inr),2) as avg_order_value,
		round(avg(cast(f.review_score as float)),2) as avg_review_score,
		sum(cast(f.is_late_delivery as int)) as late_deliveries
	from fact_orders f
	join dim_date d on f.date_sk = d.date_sk
	where d.year = @year and f.order_status = 'delivered'
	group by d.month, d.month_name
	order by d.month;
end;
go

exec usp_MonthlyRevenue @year = 2018;
go


-- Q10: SP2 - seller performance report
create or alter procedure usp_SellerPerformance
	@top_n int = 10, 
	@state nvarchar(10) = null
as
begin
	set nocount on;

	select top (@top_n)
		ds.seller_id, ds.city, ds.state,
		count(distinct f.order_id) as total_orders,
		round(sum(f.price_inr),2) as total_revenue,
		round(avg(f.price_inr),2) as avg_order_value,
		round(avg(cast(f.delivery_days as float)),1) as avg_delivery_days,
		round(avg(cast(f.review_score as float)), 2) as avg_review,
		sum(cast(f.is_late_delivery as int)) as late_deliveries,
		round(sum(cast(f.is_late_delivery as int))*100 / count(*),2) as late_rate_pct
	from fact_orders f
	join dim_seller ds on f.seller_sk = ds.seller_sk
	where f.order_status = 'delivered' and (@state is null or ds.state = @state)
	group by ds.seller_id, ds.city, ds.state
	order by total_revenue desc
end;
go

exec usp_SellerPerformance @top_n = 10, @state = null;
go


-- Q11: SP3 - customer segmentation
create or alter procedure usp_CustomerSegmentation
as
begin 
	set nocount on;

	with customer_metrics as (
		select
			dc.customer_unique_id, dc.state,
			count(distinct f.order_id) as order_count,
			round(sum(f.price_inr),2) as lifetime_value,
			round(avg(f.price_inr),2) as avg_order_value,
			max(d.full_date) as last_order_date
		from fact_orders f
		join dim_customer dc on f.customer_sk = dc.customer_sk
		join dim_date d on f.date_sk = d.date_sk
		where f.order_status = 'delivered'
		group by dc.customer_unique_id, dc.state
	)
	select
		customer_unique_id, state, order_count, 
		lifetime_value, avg_order_value, last_order_date,
		case
			when order_count >=5
				and lifetime_value >=50000 then 'VIP'
			when order_count >=3
				and lifetime_value >=20000 then 'Loyal'
			when order_count >=2 then 'Returning'
			else 'One-Time'
		end as customer_segment,
		datediff(day, last_order_date,
		cast('2018-12-31' as date)) as days_since_last_order
	from customer_metrics
	order by lifetime_value desc;
end;
go

exec usp_CustomerSegmentation;
go


-- category 4: query optimization (before / after execution plan)

-- before: slow query(no index, function on column)
-- run this, check execution plan (ctrl+M in SSMS)
select * from fact_orders
where year(cast(date_sk as nvarchar)) = 2018;

-- after: optimized version
-- add index first
create index idx_fact_date on fact_orders(date_sk)
include (price_inr, order_status);

-- then run optimized query:
select
	date_sk, sum(price_inr) as revenue
from fact_orders
where date_sk between 20180101 and 20181231
	and	order_status = 'delivered'
group by date_sk
order by date_sk;


-- category 5: views
create or alter view vw_daily_sales as 
select
	d.full_date, d.year, d.month_name, d.day_of_week, d.is_weekend,
	count(distinct f.order_id) as orders,
	count(distinct f.customer_sk) as customers,
	round(sum(f.price_inr),2) as revenue_inr,
	round(avg(f.price_inr),2) as avg_order_value,
	round(avg(cast(f.review_score as float)),2) as avg_review
from fact_orders f
join dim_date d on f.date_sk = d.date_sk
where f.order_status = 'delivered'
group by d.full_date, d.year, d.month_name, d.day_of_week, d.is_weekend;
go