package cmd

import (
	"github.com/SwissDataScienceCenter/renku-data-services/components/renku_session_services/api_proxy/pkg/apiproxy"
	"github.com/SwissDataScienceCenter/renku-data-services/components/renku_session_services/api_proxy/pkg/log"
)

func Main() {
	log.SetupLogging()
	apiproxy.Run()
}
