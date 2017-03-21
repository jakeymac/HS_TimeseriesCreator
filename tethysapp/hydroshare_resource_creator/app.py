from tethys_sdk.base import TethysAppBase, url_map_maker


class HydroshareResourceCreator(TethysAppBase):
    """
    Tethys app class for HydroShare Resource Creator.
    """

    name = 'HydroShare Resource Creator'
    index = 'hydroshare_resource_creator:home'
    icon = 'hydroshare_resource_creator/images/tool.svg'
    package = 'hydroshare_resource_creator'
    root_url = 'hydroshare-resource-creator'
    color = '#2ecc71'
    description = 'Create HydroShare resources using the CUAHSI HydroClient'
    enable_feedback = False
    feedback_emails = []

        
    def url_maps(self):
        """
        Add controllers
        """
        UrlMap = url_map_maker(self.root_url)

        url_maps = (UrlMap(name='home',
                           url='hydroshare-resource-creator',
                           controller='hydroshare_resource_creator.controllers.home'),
                    UrlMap(name='chart_data',
                           url='chart_data/{res_id}',
                           controller='hydroshare_resource_creator.controllers.chart_data'),
                    UrlMap(name='write_file',
                           url='write_file',
                           controller='hydroshare_resource_creator.controllers.write_file'),
                    UrlMap(name='response',
                           url='response',
                           controller='hydroshare_resource_creator.controllers.response'),
                    UrlMap(name='create_layer',
                           url='create_layer/{fun_type}/{res_id}/{res_type}',
                           controller='hydroshare_resource_creator.controllers.create_layer'),
                      UrlMap(name='temp_waterml',
                           url='temp_waterml/{id}',
                           controller='hydroshare_resource_creator.controllers.temp_waterml'),

                    UrlMap(name='login_callback',
                           url='login-callback',
                           controller='hydroshare_resource_creator.controllers.login_callback'),
                    UrlMap(name='login_test',
                           url='login-test',
                           controller='hydroshare_resource_creator.controllers.login_test'),

        )

        return url_maps