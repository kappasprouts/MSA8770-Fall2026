--
-- PostgreSQL database dump
--

\restrict sGGtokSmEE2lgpQ6bXKBQniTWm1JwgEJ5igrxbz5CmuHr7AadJLbngSw8iltXr3

-- Dumped from database version 16.15 (Debian 16.15-1.pgdg12+2)
-- Dumped by pg_dump version 16.15 (Debian 16.15-1.pgdg12+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: system_users; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.system_users (user_id, full_name, email, role, is_active, created_at, password) VALUES ('USR001', 'Lionel Haaland', 'lionel.haaland@riverview.com', 'ADMISSIONS_OFFICER', true, '2026-10-21 19:27:09.434071+00', 'OfficerDemo2026!');
INSERT INTO public.system_users (user_id, full_name, email, role, is_active, created_at, password) VALUES ('USR002', 'Caitlin Reese', 'caitlin.reese@riverview.com', 'DEAN', true, '2026-10-21 19:27:09.434071+00', 'DeanDemo2026!');
INSERT INTO public.system_users (user_id, full_name, email, role, is_active, created_at, password) VALUES ('USR003', 'Erling Mbappe', 'erling.mbappe@riverview.com', 'IT_SUPPORT', true, '2026-10-21 19:27:09.434071+00', 'ITDemo2026!');


--
-- PostgreSQL database dump complete
--

\unrestrict sGGtokSmEE2lgpQ6bXKBQniTWm1JwgEJ5igrxbz5CmuHr7AadJLbngSw8iltXr3

