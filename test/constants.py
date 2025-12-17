from typing import Final

envidat_sample_response: Final[str] = """
{
    "@context": "http://schema.org",
    "@type": "https://schema.org/Dataset",
    "url": "https://envidat.ch/#/metadata/ch2014",
    "@id": "https://doi.org/10.16904/12",
    "identifier": "https://doi.org/10.16904/12",
    "sameAs": {
        "@type": "Dataset",
        "@id": "https://envidat.ch/#/metadata/c8696023-5622-481d-952a-13f88c35e9fe"
    },
    "inLanguage": {
        "alternateName": "eng",
        "@type": "Language",
        "name": "English"
    },
    "publisher": {
        "@type": "Organization",
        "name": "EnviDat"
    },
    "contentSize": "33.0 GB",
    "size": "33.0 GB",
    "datePublished": "2017",
    "creator": [
        {
            "@type": "Person",
            "name": "Schoegl, Sebastian",
            "givenName": "Sebastian",
            "familyName": "Schoegl",
            "affiliation": [
                {
                    "@type": "Organization",
                    "name": "WSL Institute for Snow and Avanche Research SLF"
                }
            ]
        },
        {
            "@type": "Person",
            "name": "Marty, Christoph",
            "givenName": "Christoph",
            "familyName": "Marty",
            "affiliation": [
                {
                    "@type": "Organization",
                    "name": "WSL Institute for Snow and Avanche Research SLF"
                }
            ]
        },
        {
            "@type": "Person",
            "name": "Bavay, Mathias",
            "givenName": "Mathias",
            "familyName": "Bavay",
            "affiliation": [
                {
                    "@type": "Organization",
                    "name": "WSL Institute for Snow and Avanche Research SLF"
                },
                {
                    "@type": "Organization",
                    "name": "SLF"
                }
            ],
            "@id": "0000-0002-5039-1578"
        },
        {
            "@type": "Person",
            "name": "Lehning, Michael",
            "givenName": "Michael",
            "familyName": "Lehning",
            "affiliation": [
                {
                    "@type": "Organization",
                    "name": "WSL Institute for Snow and Avanche Research SLF"
                }
            ]
        }
    ],
    "author": [
        {
            "@type": "Person",
            "name": "Schoegl, Sebastian",
            "givenName": "Sebastian",
            "familyName": "Schoegl",
            "affiliation": [
                {
                    "@type": "Organization",
                    "name": "WSL Institute for Snow and Avanche Research SLF"
                }
            ]
        },
        {
            "@type": "Person",
            "name": "Marty, Christoph",
            "givenName": "Christoph",
            "familyName": "Marty",
            "affiliation": [
                {
                    "@type": "Organization",
                    "name": "WSL Institute for Snow and Avanche Research SLF"
                }
            ]
        },
        {
            "@type": "Person",
            "name": "Bavay, Mathias",
            "givenName": "Mathias",
            "familyName": "Bavay",
            "affiliation": [
                {
                    "@type": "Organization",
                    "name": "WSL Institute for Snow and Avanche Research SLF"
                },
                {
                    "@type": "Organization",
                    "name": "SLF"
                }
            ],
            "@id": "0000-0002-5039-1578"
        },
        {
            "@type": "Person",
            "name": "Lehning, Michael",
            "givenName": "Michael",
            "familyName": "Lehning",
            "affiliation": [
                {
                    "@type": "Organization",
                    "name": "WSL Institute for Snow and Avanche Research SLF"
                }
            ]
        }
    ],
    "keywords": "CH2011, CH2014, CLIMATE CHANGE, SNOW DEPTH, SNOW WATER EQUIVALENT",
    "temporal": [
        "2017-02-07"
    ],
    "distribution": [
        {
            "@type": "DataDownload",
            "contentUrl": "https://envidat-doi.os.zhdk.cloud.switch.ch/?prefix=10.16904_12",
            "name": "All resources in one place"
        },
        {
            "@type": "DataDownload",
            "contentUrl": "http://ch2014-impacts.ch/",
            "contentSize": 0,
            "encodingFormat": "No Info",
            "name": "CH2014 REPORT"
        },
        {
            "@type": "DataDownload",
            "contentUrl": "https://envicloud.wsl.ch/#/?prefix=doi/12/ch2014/",
            "contentSize": 35433480192,
            "encodingFormat": "No Info",
            "name": "Dataset"
        },
        {
            "@type": "DataDownload",
            "contentUrl": "https://www.envidat.ch/dataset/c8696023-5622-481d-952a-13f88c35e9fe/resource/41555ebb-435b-40a3-b338-826e1c3172e3/download/graubunden_input.tar.bz2",
            "contentSize": 1208440,
            "encodingFormat": "application/x-tar",
            "name": "Graubunden input"
        },
        {
            "@type": "DataDownload",
            "contentUrl": "https://www.envidat.ch/dataset/c8696023-5622-481d-952a-13f88c35e9fe/resource/ad886f54-bc18-4972-9fd0-db9bda3f7dd5/download/aare_input.tar.bz2",
            "contentSize": 360212,
            "encodingFormat": "application/x-tar",
            "name": "Aare input"
        }
    ],
    "name": "Alpine3D simulations of future climate scenarios CH2014",
    "description": "# Overview\\r\\n\\r\\nThe CH2014-Impacts initiative is a concerted national effort to describe impacts of climate change in Switzerland quantitatively, drawing on the scientific resources available in Switzerland today. The initiative links the recently developed Swiss Climate Change Scenarios CH2011 with an evolving base of quantitative impact models. The use of a common climate data set across disciplines and research groups sets a high standard of consistency and comparability of results. Impact studies explore the wide range of climatic changes in temperature and precipitation projected in CH2011 for the 21st century, which vary with the assumed global level of greenhouse gases, the time horizon, the underlying climate model, and the geographical region within Switzerland. The differences among climate projections are considered using three greenhouse gas scenarios, three future time periods in the 21st century, and three climate uncertainty levels (Figure 1). Impacts are shown with respect to the reference period 1980-2009 of CH2011, and add to any impacts that have already emerged as a result of earlier climate change.\\r\\n\\r\\n# Experimental Setup\\r\\n\\r\\nFuture snow cover changes are simulated with the physics-based model Alpine3D (Lehning et al., 2006). It is applied to two regions: The canton of Graub\u00fcnden and the Aare catchment. These domains are modeled with a Digital Elevation Model (DEM) with a resolution of 200 m \u00d7 200 m. This defines the simulation grid that has to be filled with land cover data and downscaled meteorological input data for each cell for the time period of interest at hourly resolution. The reference data set consists of automatic weather station data. All meteorological input parameters are spatially interpolated to the simulation grid. The reference period comprises only thirteen years (1999\u20132012), because the number of available high elevation weather stations for earlier times is not sufficient to achieve unbiased distribution of the observations with elevation. The model uses projected temperature and precipitation changes for all greenhouse gas scenarios (A1B, A2, and RCP3PD) and CH2011 time periods (2035, 2060, and 2085).\\r\\n\\r\\n# Data\\r\\n\\r\\nSnow cover changes are projected to be relatively small in the near term (2035) (Figure 5.1 top), in particular at higher elevations above 2000 m asl. As shown by Bavay et al. (2013) the spread in projected snow cover for this period is greater between different climate model chains (Chapter 3) than between the reference period and the model chain exhibiting the most moderate change. In the 2085 period much larger changes with the potential to fundamentally transform the snow dominated alpine area become apparent (Figure 5.1 bottom). These changes include a shortening of the snow season by 5\u20139 weeks for the A1B scenario. This is roughly equivalent to an elevation shift of 400\u2013800 m. The slight increase of winter precipitation and therefore snow fall projected in the CH2011 scenarios (with high associated uncertainty) can no longer compensate for the effect of increasing winter temperatures even at high elevations. In terms of Snow Water Equivalents (SWE), the projected reduction is up to two thirds toward the end of the century (2085). A continuous snow cover will be restricted to a shorter time period and/or to regions at increasingly high elevation. In Bern, for example, the number of days per year with at least 5 cm snow depth will decrease by 90% from now 20 days to only 2 days on average.\\r\\n",
    "dateCreated": "2017-02-07T08:21:09.738064",
    "dateModified": "2025-11-07T09:29:55.466890",
    "version": "1",
    "license": "https://opendefinition.org/licenses/odc-odbl"
}
"""  # noqa: E501
