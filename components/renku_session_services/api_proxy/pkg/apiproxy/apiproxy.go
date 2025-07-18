package apiproxy

import (
	"fmt"
	"log/slog"
	"net/url"
	"os"

	"github.com/SwissDataScienceCenter/renku-data-services/components/renku_session_services/api_proxy/pkg/config"
	"github.com/SwissDataScienceCenter/renku-data-services/components/renku_session_services/api_proxy/pkg/tokenstore"
	"github.com/labstack/echo/v4"
	"github.com/labstack/echo/v4/middleware"
)

type ApiProxy struct {
	config *config.Config
	store  *tokenstore.TokenStore
}

func (ap *ApiProxy) RegisterHandlers(e *echo.Echo, commonMiddlewares ...echo.MiddlewareFunc) {
	dataApiURL := ap.config.RenkuURL.JoinPath("api/data")
	sessionURL := dataApiURL.JoinPath("sessions", ap.config.SessionID)
	sessionPath := sessionURL.EscapedPath()

	tokenMiddleware := ap.getTokenMiddleware()
	dataServiceProxy := proxyFromURL(dataApiURL)

	slog.Info("setting up reverse proxy for session", "path", sessionPath)
	e.Group(sessionPath, append(commonMiddlewares, tokenMiddleware, dataServiceProxy)...)
}

func (ap *ApiProxy) getTokenMiddleware() echo.MiddlewareFunc {
	return func(next echo.HandlerFunc) echo.HandlerFunc {
		return func(c echo.Context) error {
			existingToken := c.Request().Header.Get(echo.HeaderAuthorization)
			if existingToken != "" {
				return next(c)
			}
			token, err := ap.store.GetValidRenkuAccessToken()
			if err != nil {
				slog.Info("token could not be loaded", "error", err)
				return next(c)
			}
			c.Request().Header.Set(echo.HeaderAuthorization, fmt.Sprintf("Bearer %s", token))
			return next(c)
		}
	}
}

func proxyFromURL(url *url.URL) echo.MiddlewareFunc {
	if url == nil {
		slog.Error("cannot create a proxy from a nil URL")
		os.Exit(1)
	}
	config := middleware.ProxyConfig{
		// // the skipper is used to log only
		// Skipper: func(c echo.Context) bool {
		// 	// slog.Info("PROXY", "requestID", utils.GetRequestID(c), "destination", url.String())
		// 	return false
		// },
		Balancer: middleware.NewRoundRobinBalancer([]*middleware.ProxyTarget{
			{
				Name: url.String(),
				URL:  url,
			}}),
	}
	return middleware.ProxyWithConfig(config)
}

type ApiProxyOption func(*ApiProxy)

func WithConfig(config config.Config) ApiProxyOption {
	return func(ap *ApiProxy) {
		ap.config = &config
	}
}

func WithTokenStore(store *tokenstore.TokenStore) ApiProxyOption {
	return func(ap *ApiProxy) {
		ap.store = store
	}
}

func NewApiProxy(options ...ApiProxyOption) (apiProxy *ApiProxy, err error) {
	server := ApiProxy{}
	for _, opt := range options {
		opt(&server)
	}
	return &server, nil
}
