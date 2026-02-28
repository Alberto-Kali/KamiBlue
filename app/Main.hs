{-# LANGUAGE DataKinds #-}
{-# LANGUAGE TypeOperators #-}

module Main where

import ApiTypes
import RequestController
import Servant
import Servant.Server
import Network.Wai.Handler.Warp
import Network.Wai (Application)
import Servant.API.WebSocket (WebSocket)
import System.Directory

type SquareAPI = "hello" :> Get '[JSON] String
            :<|> "addScript" :> ReqBody '[JSON] AddScriptRequest :> Post '[JSON] AddScriptResponse
            :<|> "listScripts" :> Get '[JSON] [String]
            :<|> "runScript" :> Capture "name" String :> "ws" :> WebSocket

squareAPI :: Proxy SquareAPI
squareAPI = Proxy

server :: Server SquareAPI
server = helloHandler
    :<|> addScriptHandler
    :<|> getScriptsHandler
    :<|> scriptWebSocketHandler

helloHandler :: Handler String
helloHandler = return "C‑script server is running"

app :: Application
app = serve squareAPI server

main :: IO ()
main = do
  putStrLn "Starting C‑script server on port 7485..."
  -- Создаём необходимые папки, если их нет
  mapM_ (createDirectoryIfMissing True) ["sources", "bin", "tmp"]
  run 7485 app