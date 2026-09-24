ALTER TABLE meetings
ADD COLUMN client_name TEXT NOT NULL DEFAULT 'A classificar';

ALTER TABLE meetings
ADD COLUMN project_name TEXT NOT NULL DEFAULT 'A classificar';
