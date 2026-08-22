-- Agregar columna FilePath para almacenar archivos en disco en vez de LONGBLOB
ALTER TABLE HUBMAIL_Attachments ADD COLUMN FilePath VARCHAR(1000) NULL AFTER Size;
