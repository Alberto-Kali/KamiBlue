{-# LANGUAGE DeriveGeneric #-}
module ApiTypes where

import Data.Aeson
import GHC.Generics

-- Запрос на добавление нового скрипта
data AddScriptRequest = AddScriptRequest
  { name    :: String  -- имя скрипта (используется как имя папки и бинарника)
  , content :: String  -- содержимое main.c
  } deriving (Generic, Show)

instance FromJSON AddScriptRequest
instance ToJSON AddScriptRequest

-- Ответ на добавление скрипта
data AddScriptResponse = AddScriptResponse
  { success    :: Bool
  , message    :: String
  , binaryPath :: Maybe FilePath  -- путь к скомпилированному бинарнику в bin/
  } deriving (Generic, Show)

instance ToJSON AddScriptResponse