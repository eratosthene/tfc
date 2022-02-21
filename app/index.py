from flask_appbuilder import IndexView
from flask_appbuilder.views import expose
from flask_appbuilder.models.mongoengine.interface import MongoEngineInterface
from app.models import Figure, Franchise, Faction, Tooling, Category

class MyIndexView(IndexView):
    index_template = "index.html"

    @expose('/')
    def index(self):
        self.update_redirect()
        num_figures = Figure.objects().count()
        by_franchise = []
        for f in Franchise.objects().order_by('start_year'):
            fn = Figure.objects(franchise__contains=f.id).count()
            by_franchise.append({'franchise': f, 'total': fn})
        by_faction = []
        for f in Faction.objects().order_by('name'):
            fn = Figure.objects(faction=f.id).count()
            by_faction.append({'faction': f, 'total': fn})
        by_tooling = []
        for f in Tooling.objects().order_by('name'):
            fn = Figure.objects(tooling=f.id).count()
            by_tooling.append({'tooling': f, 'total': fn})
        by_category = []
        for f in Category.objects().order_by('name'):
            fn = Figure.objects(categories__contains=f.id).count()
            by_category.append({'category': f, 'total': fn})
        return self.render_template(self.index_template, appbuilder=self.appbuilder, 
                num_figures=num_figures, by_franchise=by_franchise, by_faction=by_faction,
                by_tooling=by_tooling, by_category=by_category)

