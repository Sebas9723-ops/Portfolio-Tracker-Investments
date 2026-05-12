-- Migration 015: rename legacy 'balanced' investor_profile to 'base'
-- 'balanced' was the original default but the engine only recognizes
-- 'conservative', 'base', and 'aggressive'.

ALTER TABLE user_settings
  ALTER COLUMN investor_profile SET DEFAULT 'base';

UPDATE user_settings
  SET investor_profile = 'base'
  WHERE investor_profile = 'balanced';
