{-# LANGUAGE OverloadedStrings #-}
{-# LANGUAGE ScopedTypeVariables #-}
module RequestController
  ( addScriptHandler
  , getScriptsHandler
  , scriptWebSocketHandler
  ) where

import ApiTypes
import Control.Concurrent (forkIO, killThread, threadDelay)
import Control.Concurrent.STM
import Control.Exception (try, catch, SomeException)
import Control.Monad (forM_, forever, unless, when, filterM)
import Control.Monad.IO.Class (liftIO)
import qualified Data.ByteString.Lazy as BL
import qualified Data.ByteString.Lazy.Char8 as BL8   -- для pack String
import Data.Text (Text)
import qualified Data.Text as T
import System.Directory
import System.Exit (ExitCode(..))
import System.FilePath ((</>))
import System.IO (hFlush, hGetLine, hPutStrLn, Handle, hClose, hGetContents)
import System.Process (createProcess, proc, CreateProcess(..), StdStream(..), waitForProcess)
import qualified Network.WebSockets as WS
import Servant
import Control.Exception (catch, IOException, SomeException)
import Network.WebSockets (ConnectionException)

-- ----------------------------------------------------------------------
--  Добавление скрипта: копирование шаблона, замена main.c, компиляция
-- ----------------------------------------------------------------------
addScriptHandler :: AddScriptRequest -> Handler AddScriptResponse
addScriptHandler req = liftIO $ do
  let scriptName = name req
      scriptContent = content req

  -- Проверка имени: разрешены только буквы, цифры и подчёркивание
  if not (all (\c -> isAlphaNum c || c == '_') scriptName)
    then return $ AddScriptResponse False "Invalid script name: use only letters, digits, underscore" Nothing
    else do
      let srcDir   = "sources" </> scriptName
          binDir   = "bin"
          templateDir = "template"

      -- Проверяем, что папка template существует
      templateExists <- doesDirectoryExist templateDir
      if not templateExists
        then return $ AddScriptResponse False "Template directory not found" Nothing
        else do
          -- Удаляем старую папку скрипта, если существует
          srcExists <- doesDirectoryExist srcDir
          when srcExists $ removeDirectoryRecursive srcDir

          -- Копируем шаблон
          copyDirectory templateDir srcDir

          -- Заменяем main.c (шаблон обязан содержать этот файл)
          let mainPath = srcDir </> "src" </> scriptName ++ ".c"
          BL.writeFile mainPath (BL8.pack scriptContent)   -- используем BL8.pack

          -- Запускаем make в srcDir
          makeResult <- (try $ readProcessWithExitCode' "make" ["-C", srcDir]) :: IO (Either SomeException (ExitCode, String, String))
          case makeResult of
            Left err ->
              return $ AddScriptResponse False ("Compilation error: " ++ show err) Nothing
            Right (exitCode, _stdout, stderr) ->
              if exitCode /= ExitSuccess
                then return $ AddScriptResponse False ("Compilation failed:\n" ++ stderr) Nothing
                else do
                  -- Ожидаем, что make создаст бинарник с именем, равным scriptName
                  let binarySrc = srcDir </> scriptName
                  binExists <- doesFileExist binarySrc
                  if not binExists
                    then return $ AddScriptResponse False "Compilation succeeded but binary not found" Nothing
                    else do
                      -- Создаём папку bin, если её нет
                      createDirectoryIfMissing True binDir
                      let binaryDst = binDir </> scriptName
                      copyFile binarySrc binaryDst
                      return $ AddScriptResponse True "Script added and compiled successfully" (Just binaryDst)

-- ----------------------------------------------------------------------
--  Получение списка всех скомпилированных скриптов (файлы в bin/)
-- ----------------------------------------------------------------------
getScriptsHandler :: Handler [String]
getScriptsHandler = liftIO $ do
  createDirectoryIfMissing True "bin"
  contents <- listDirectory "bin"
  -- Оставляем только файлы (не директории)
  files <- filterM doesFileExist (map ("bin" </>) contents)
  return $ map takeFileName files
  where
    takeFileName = reverse . takeWhile (/= '/') . reverse

-- ----------------------------------------------------------------------
--  WebSocket‑обработчик для запуска скрипта и двустороннего I/O
-- ----------------------------------------------------------------------
scriptWebSocketHandler :: String -> WS.Connection -> Handler ()
scriptWebSocketHandler scriptName conn = liftIO $ do
  let binaryPath = "bin" </> scriptName
  exists <- doesFileExist binaryPath
  unless exists $ do
    WS.sendClose conn ("Binary not found: " <> T.pack scriptName)
    return ()

  toStdin  <- newTQueueIO
  fromStdout <- newTQueueIO
  fromStderr <- newTQueueIO

  (Just inH, Just outH, Just errH, processHandle) <- createProcess
    (proc binaryPath [])
    { std_in  = CreatePipe
    , std_out = CreatePipe
    , std_err = CreatePipe
    , close_fds = True
    }

  -- читаем stdout
  stdoutReader <- forkIO $ do
    let loop = do
          line <- hGetLine outH
          atomically $ writeTQueue fromStdout (T.pack line)
          loop
    loop `catch` (\(_ :: IOError) -> return ())

  -- читаем stderr
  stderrReader <- forkIO $ do
    let loop = do
          line <- hGetLine errH
          atomically $ writeTQueue fromStderr (T.pack line)
          loop
    loop `catch` (\(_ :: IOError) -> return ())

  -- читаем сообщения от клиента (WebSocket) → toStdin
  stdinWriter <- forkIO $ forever $ do
    msg <- WS.receiveData conn `catch` (\(_ :: WS.ConnectionException) -> return "")
    when (msg /= "") $ atomically $ writeTQueue toStdin msg

  -- отправляем stdout/stderr клиенту
  senderThread <- forkIO $ do
    let loop = do
          outMsg <- atomically $ tryReadTQueue fromStdout
          errMsg <- atomically $ tryReadTQueue fromStderr
          case (outMsg, errMsg) of
            (Nothing, Nothing) -> threadDelay 1000
            _ -> do
              mapM_ (WS.sendTextData conn . ("[stdout] " <>)) outMsg
              mapM_ (WS.sendTextData conn . ("[stderr] " <>)) errMsg
          loop
    loop `catch` (\(_ :: WS.ConnectionException) -> return ())

  -- пишем в stdin процесса
  stdinFeeder <- forkIO $ do
    let loop = do
          msg <- atomically $ readTQueue toStdin
          hPutStrLn inH (T.unpack msg)
          hFlush inH
          loop
    loop `catch` (\(_ :: IOError) -> return ())

  exitCode <- waitForProcess processHandle
  threadDelay 100000  -- 100ms

  hClose inH `catch` (\(_ :: IOError) -> return ())
  hClose outH `catch` (\(_ :: IOError) -> return ())
  hClose errH `catch` (\(_ :: IOError) -> return ())

  killThread stdoutReader
  killThread stderrReader
  killThread stdinWriter
  killThread senderThread
  killThread stdinFeeder

  WS.sendClose conn (T.pack $ "Process finished with exit code: " ++ show exitCode)
    `catch` (\(_ :: WS.ConnectionException) -> return ())
  
-- ----------------------------------------------------------------------
--  Вспомогательные функции
-- ----------------------------------------------------------------------
isAlphaNum :: Char -> Bool
isAlphaNum c = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9')

-- Рекурсивное копирование директории
copyDirectory :: FilePath -> FilePath -> IO ()
copyDirectory src dst = do
  createDirectoryIfMissing True dst
  contents <- listDirectory src
  forM_ contents $ \item -> do
    let srcPath = src </> item
        dstPath = dst </> item
    isDir <- doesDirectoryExist srcPath
    if isDir
      then copyDirectory srcPath dstPath
      else copyFile srcPath dstPath

-- Запуск внешней программы с возвратом кода выхода и выводов
readProcessWithExitCode' :: FilePath -> [String] -> IO (ExitCode, String, String)
readProcessWithExitCode' cmd args = do
  (_, Just outH, Just errH, ph) <- createProcess (proc cmd args) { std_out = CreatePipe, std_err = CreatePipe }
  exitCode <- waitForProcess ph
  outStr <- hGetContents outH
  errStr <- hGetContents errH
  -- Принудительно вычитываем, так как hGetContents ленивое
  length outStr `seq` length errStr `seq` return ()
  return (exitCode, outStr, errStr)