--
-- PostgreSQL database dump
--

\restrict 9Xm6qNv8ldkWW8aVeSXtz9utbhs2oFezQXa52Rye1Ea8ks4IZrnNhMBaPDi220x

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

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: system_users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_users (
    user_id character varying(20) NOT NULL,
    full_name character varying(100) NOT NULL,
    email character varying(150) NOT NULL,
    role character varying(30) NOT NULL,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    password text,
    CONSTRAINT system_users_role_check CHECK (((role)::text = ANY ((ARRAY['ADMISSIONS_OFFICER'::character varying, 'DEAN'::character varying, 'IT_SUPPORT'::character varying])::text[])))
);


--
-- Name: system_users system_users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_users
    ADD CONSTRAINT system_users_email_key UNIQUE (email);


--
-- Name: system_users system_users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_users
    ADD CONSTRAINT system_users_pkey PRIMARY KEY (user_id);


--
-- PostgreSQL database dump complete
--

\unrestrict 9Xm6qNv8ldkWW8aVeSXtz9utbhs2oFezQXa52Rye1Ea8ks4IZrnNhMBaPDi220x

